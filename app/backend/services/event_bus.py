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

**Internal channel is a separate, unbounded path — not `subscribe()`.**
`publish()` routes any `internal.`-prefixed message to `subscribe_internal()`
only, never into the same bounded, drop-oldest, coalesced mailboxes browser
SSE connections use. `DeviceRegistry` is the sole consumer of
`internal.device_arrived`/`internal.device_departed`, and it must never
silently lose one — a dropped arrival/departure permanently desyncs
`present` and, downstream, `SupervisorService`'s desired set, with no
resync mechanism to recover it (unlike a browser tab, which can always be
handed a fresh `snapshot`). Sharing the public, best-effort channel used to
mean the registry's own subscription could both drop a hotplug message on
overflow *and* never learn about `RESYNC_EVENT_NAME` to recover from it —
using a dedicated, unbounded queue removes the possibility of either.
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

_INTERNAL_EVENT_PREFIX = "internal."
"""`publish()` routes any message whose `event` starts with this prefix to
`subscribe_internal()`'s dedicated channel instead of the public, bounded
subscriber mailboxes — see the module docstring."""


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
        self._internal_subscribers: set[asyncio.Queue[SseMessage]] = set()

    async def subscribe_internal(self) -> AsyncIterator[SseMessage]:
        """Yield every `internal.`-prefixed message published, on a dedicated unbounded queue.

        For `DeviceRegistry`'s hotplug consumer only (see module docstring)
        — unbounded because there is exactly one long-lived internal
        consumer, always draining, never a slow browser tab, so nothing here
        needs the public channel's bounded/drop-oldest/resync machinery.
        """
        queue: asyncio.Queue[SseMessage] = asyncio.Queue()
        self._internal_subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._internal_subscribers.discard(queue)

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
        An `internal.`-prefixed message is routed exclusively to
        `subscribe_internal()`'s dedicated channel (module docstring) — it
        never reaches a public subscriber's mailbox at all, since every
        public consumer (`routers/events.py`) discards it anyway.
        """
        if message.event.startswith(_INTERNAL_EVENT_PREFIX):
            self._deliver_to_internal_subscribers(message)
            return

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
            # Only remove this device's dict entry if it still points at
            # *this* task. `publish()` calls `existing_task.cancel()` then
            # immediately stores a new task in the same dict slot — if this
            # `finally` popped unconditionally, a task that lost the
            # cancel-vs-overwrite race would still run to completion (it
            # already passed the `except CancelledError: return` above) and
            # delete the *new*, superseding task's entry out from under it,
            # silently breaking coalescing under load for every publish
            # after that. Comparing identity against `asyncio.current_task()`
            # makes the pop a no-op whenever this task has already been
            # superseded, which is exactly when it must not touch the dict.
            if self._pending_device_changed_tasks.get(device_id) is asyncio.current_task():
                self._pending_device_changed_tasks.pop(device_id, None)
        self._deliver_to_subscribers(message)

    def _deliver_to_internal_subscribers(self, message: SseMessage) -> None:
        """Enqueue `message` for every internal subscriber's unbounded queue. Never drops."""
        for queue in self._internal_subscribers:
            queue.put_nowait(message)

    def _deliver_to_subscribers(self, message: SseMessage) -> None:
        """Enqueue `message` for every current subscriber, applying drop-oldest on overflow."""
        for subscriber in self._subscribers:
            self._enqueue_for_subscriber(subscriber, message)

    def _enqueue_for_subscriber(self, subscriber: _Subscriber, message: SseMessage) -> None:
        """Put `message` on one subscriber's queue; on overflow, drop everything queued so far.

        The previous behaviour dropped only the single oldest entry and set
        `needs_resync` — but with a 256-slot queue that leaves up to ~255
        already-stale messages still queued *behind* the fresh `snapshot`
        `subscribe()` sends first on `needs_resync`. Since the store on the
        frontend merges each event unconditionally rather than discarding
        anything older than the snapshot, those replayed-stale messages then
        overwrite the just-delivered correct state, and the client stays
        wrong until that specific device next changes. Draining the whole
        queue here means the fresh `snapshot` is genuinely the next thing
        this subscriber receives, with nothing older left to replay over it.
        """
        try:
            subscriber.queue.put_nowait(message)
        except asyncio.QueueFull:
            while not subscriber.queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(message)
            subscriber.needs_resync = True

    def subscriber_count(self) -> int:
        """Return the number of currently-connected subscribers."""
        return len(self._subscribers)
