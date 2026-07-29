"""In-process pub/sub fan-out (architecture §4.3, §7.3, §12.11).

Doubles as the outbound SSE bus (`snapshot`/`device_changed`/`device_removed`/
`health`/`notice` — architecture §7.3) **and** the internal channel
`hotplug.py` and `device_registry.py` use to hand off settled USB arrivals/
departures, so every service that needs to react to another service's output
shares one fan-out primitive rather than each inventing its own callback
wiring. Every subscriber gets a bounded, drop-oldest queue — the same
discipline the relay already applies to IQ clients (module docstring of
`app.backend.relay.rtl_tcp_relay`) — so one slow browser tab can never stall
the bus for everyone else. Repeated `device_changed` events for the same
device are coalesced within a short window.

**Event-name namespace.** Names starting with `internal.` (e.g.
`hotplug.HOTPLUG_DEVICE_ARRIVED_EVENT`) and the reserved `RESYNC_EVENT_NAME`
below are never valid SSE wire events — the `/api/events` router must filter
`subscribe()`'s output down to the public names in architecture §7.3 before
forwarding anything to a browser, and must translate `RESYNC_EVENT_NAME` into
a freshly-built `snapshot` rather than relaying it literally.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.backend.interfaces.clock import Clock

DEFAULT_SUBSCRIBER_QUEUE_SIZE = 256
DEVICE_CHANGED_COALESCE_WINDOW_S = 0.1

RESYNC_EVENT_NAME = "__resync_required__"
"""Emitted to one subscriber, ahead of its next real message, after its queue
overflowed. Internal-only (see module docstring); the router must respond by
building and sending a fresh real `snapshot`, never by relaying this event
name onto the wire.
"""


@dataclass(frozen=True, slots=True)
class SseMessage:
    """One outbound Server-Sent Event: an event name plus its JSON-able payload."""

    event: str
    """The SSE event name: snapshot, device_changed, device_removed, health, or notice —
    or one of the internal-only names documented in this module's docstring."""

    data: Any
    """A Pydantic model instance from `schemas/events.py`, `schemas/device.py`, etc.,
    for a public event; an internal dataclass (e.g. `hotplug.HotplugArrival`)
    for an internal-only one."""


@dataclass(slots=True, eq=False)
class _Subscriber:
    """One `subscribe()` caller's mailbox and resync flag.

    `eq=False` keeps the dataclass's default identity-based `__eq__`/`__hash__`
    (rather than dataclass's normal field-based `__eq__`, which — combined
    with `slots=True` giving no default `__hash__` at all — would make every
    instance unhashable) so subscribers can be stored in `EventBus._subscribers`,
    a plain `set`, keyed by object identity as intended.
    """

    queue: asyncio.Queue[SseMessage] = field(default_factory=asyncio.Queue)
    needs_resync: bool = False


def _device_id_of(message: SseMessage) -> str | None:
    """Extract the device identifier a `device_changed` message concerns, if any.

    Coalescing is keyed by this value. Duck-typed against `.device_id` (the
    attribute both `schemas.device.DeviceStatus` and `hotplug.DeviceArrived`-
    like payloads could plausibly carry) rather than importing the schema, so
    this module stays a leaf with only `Clock` as a real dependency. A
    payload with no such attribute is never coalesced — it is delivered
    immediately, which is always safe (merely less bandwidth-efficient).
    """
    return getattr(message.data, "device_id", None)


class EventBus:
    """Publishes messages to every currently-subscribed connection.

    Constructed once per process and injected into every service that needs
    to notify another part of the system (`device_registry`, `hotplug`,
    `supervisor`, `eeprom`, `health`) and into the `events` router, which is
    the only consumer that forwards `subscribe()`'s output to real clients.
    """

    def __init__(
        self,
        clock: Clock,
        subscriber_queue_size: int = DEFAULT_SUBSCRIBER_QUEUE_SIZE,
        coalesce_window_s: float = DEVICE_CHANGED_COALESCE_WINDOW_S,
    ) -> None:
        """Configure the bus; `clock` drives the coalescing window deterministically in tests."""
        self._clock = clock
        self._subscriber_queue_size = subscriber_queue_size
        self._coalesce_window_s = coalesce_window_s
        self._subscribers: set[_Subscriber] = set()
        self._pending_device_changed_tasks: dict[str, asyncio.Task[None]] = {}

    async def subscribe(self) -> AsyncIterator[SseMessage]:
        """Yield every message published after subscription, until the caller stops iterating.

        On overflow (a subscriber falling behind), the oldest queued message
        is dropped and a fresh `snapshot` is forced on the next flush (via
        `RESYNC_EVENT_NAME`, yielded ahead of the next real message) so the
        client self-heals instead of drifting from reality.
        """
        subscriber = _Subscriber(queue=asyncio.Queue(maxsize=self._subscriber_queue_size))
        self._subscribers.add(subscriber)
        try:
            while True:
                if subscriber.needs_resync:
                    subscriber.needs_resync = False
                    yield SseMessage(event=RESYNC_EVENT_NAME, data=None)
                    continue
                message = await subscriber.queue.get()
                yield message
        finally:
            self._subscribers.discard(subscriber)

    def publish(self, message: SseMessage) -> None:
        """Fan `message` out to every current subscriber's queue.

        Two `device_changed` messages for the same device within the
        coalesce window are merged into one (only the later one is ever
        delivered); messages for different devices, or of a different event
        type, are never coalesced together and are delivered immediately.
        """
        if message.event != "device_changed":
            self._deliver_to_subscribers(message)
            return

        device_id = _device_id_of(message)
        if device_id is None:
            self._deliver_to_subscribers(message)
            return

        existing_task = self._pending_device_changed_tasks.get(device_id)
        if existing_task is not None:
            existing_task.cancel()
        self._pending_device_changed_tasks[device_id] = asyncio.create_task(
            self._deliver_after_coalesce_window(device_id, message),
            name=f"event-bus-coalesce-{device_id}",
        )

    async def _deliver_after_coalesce_window(self, device_id: str, message: SseMessage) -> None:
        """Wait out the coalesce window, then deliver `message` unless superseded.

        Being superseded by a newer `device_changed` for the same device is
        expressed as this task being cancelled (by a later `publish()` call)
        before the sleep completes.
        """
        try:
            await self._clock.sleep(self._coalesce_window_s)
        except asyncio.CancelledError:
            return
        finally:
            self._pending_device_changed_tasks.pop(device_id, None)
        self._deliver_to_subscribers(message)

    def _deliver_to_subscribers(self, message: SseMessage) -> None:
        """Enqueue `message` for every current subscriber, applying drop-oldest on overflow."""
        for subscriber in self._subscribers:
            self._enqueue_for_subscriber(subscriber, message)

    def _enqueue_for_subscriber(self, subscriber: _Subscriber, message: SseMessage) -> None:
        """Put `message` on one subscriber's queue, dropping its oldest entry if full."""
        try:
            subscriber.queue.put_nowait(message)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                subscriber.queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(message)
            subscriber.needs_resync = True

    def subscriber_count(self) -> int:
        """Return the number of currently-connected subscribers."""
        return len(self._subscribers)
