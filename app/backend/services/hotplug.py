"""Own the hotplug event stream (architecture §4.3).

Consumes a `HotplugSource`, debounces bursty re-enumeration, resolves
identity across the whole current candidate set, and republishes settled
arrivals/departures onto the shared `EventBus` as **internal-only** messages
(`HOTPLUG_DEVICE_ARRIVED_EVENT` / `HOTPLUG_DEVICE_DEPARTED_EVENT`) —
`DeviceRegistry` is the sole subscriber that acts on these two event names;
neither is ever forwarded onto a real SSE connection (only the public event
names in architecture §7.3 are). This indirection — rather than injecting
`DeviceRegistry` directly — is deliberate: it keeps `HotplugService`
constructible with exactly `(hotplug_source, usb_discovery, clock, event_bus)`,
matching the composition root's wiring, while still getting settled arrivals
to the registry. Also tracks whether the primary (udev) source is alive for
`GET /api/health`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.types import UsbDeviceSnapshot
from app.backend.interfaces.usb import HotplugSource
from app.backend.services import identity
from app.backend.services.event_bus import EventBus, SseMessage
from app.backend.services.identity import DeviceIdentity
from app.backend.services.usb_discovery import UsbDiscoveryService

_logger = logging.getLogger(__name__)

DEBOUNCE_COALESCE_WINDOW_S = 0.2
"""Bursty re-enumeration within this window collapses to one notification per path."""

HOTPLUG_DEVICE_ARRIVED_EVENT = "internal.device_arrived"
"""Internal-only `EventBus` event name carrying a `HotplugArrival` payload.

Never sent to a browser — `DeviceRegistry` consumes it and, once applied,
publishes the *public* `device_changed` event in its place.
"""

HOTPLUG_DEVICE_DEPARTED_EVENT = "internal.device_departed"
"""Internal-only `EventBus` event name carrying a `DeviceDeparted` payload.

Never sent to a browser, for the same reason as `HOTPLUG_DEVICE_ARRIVED_EVENT`.
"""


@dataclass(frozen=True, slots=True)
class DeviceArrived:
    """Domain event: a debounced USB device addition."""

    topology_path: str
    snapshot: UsbDeviceSnapshot
    driver_conflict: bool
    """Whether a DVB kernel driver is bound instead of the userspace driver."""


@dataclass(frozen=True, slots=True)
class DeviceDeparted:
    """Domain event: a debounced USB device removal."""

    topology_path: str


@dataclass(frozen=True, slots=True)
class HotplugArrival:
    """The full payload published for `HOTPLUG_DEVICE_ARRIVED_EVENT`.

    Bundles the arrival together with its resolved identity so
    `DeviceRegistry.apply_device_arrived(event, identity)`'s existing two-
    argument shape can be called directly from the subscriber loop without
    widening `EventBus.SseMessage.data` beyond one payload.
    """

    event: DeviceArrived
    identity: DeviceIdentity | None


class HotplugService:
    """Debounces the raw hotplug stream and republishes domain events on the event bus."""

    def __init__(
        self,
        hotplug_source: HotplugSource,
        usb_discovery: UsbDiscoveryService,
        clock: Clock,
        event_bus: EventBus,
    ) -> None:
        self._hotplug_source = hotplug_source
        self._usb_discovery = usb_discovery
        self._clock = clock
        self._event_bus = event_bus
        self._pending_debounce_tasks: dict[str, asyncio.Task[None]] = {}
        self._last_event_at_ms: int | None = None

    async def run(self) -> None:
        """Consume `hotplug_source.events()` forever, debouncing and republishing.

        Intended to run as a long-lived background task from the FastAPI
        lifespan; returns only when the source's event stream ends (normally
        because `close()` was called).
        """
        async for event in self._hotplug_source.events():
            self._last_event_at_ms = event.observed_at_ms

            existing_task = self._pending_debounce_tasks.get(event.topology_path)
            if existing_task is not None:
                existing_task.cancel()
            self._pending_debounce_tasks[event.topology_path] = asyncio.create_task(
                self._debounce_and_dispatch(event.topology_path, event.action),
                name=f"hotplug-debounce-{event.topology_path}",
            )

    async def _debounce_and_dispatch(self, topology_path: str, action: str) -> None:
        """Wait out the coalesce window, then apply the latest settled action.

        Being superseded by a newer event for the same path is expressed as
        this task being cancelled (by `run()`) before the sleep completes, so
        only the last action within the window is ever dispatched.
        """
        try:
            await self._clock.sleep(DEBOUNCE_COALESCE_WINDOW_S)
        except asyncio.CancelledError:
            return
        finally:
            self._pending_debounce_tasks.pop(topology_path, None)

        if action == "add":
            self._dispatch_arrival(topology_path)
        else:
            self._event_bus.publish(
                SseMessage(
                    event=HOTPLUG_DEVICE_DEPARTED_EVENT,
                    data=DeviceDeparted(topology_path=topology_path),
                )
            )

    def _dispatch_arrival(self, topology_path: str) -> None:
        """Resolve identity across the whole current candidate set and publish the arrival.

        Re-enumerates via `usb_discovery` rather than trusting the raw
        hotplug event's payload, since identity uniqueness is a property of
        the *whole* snapshot set (architecture §5.1), not one device in
        isolation. If the device has already left again by the time this
        fires (it settled as absent before the debounce window elapsed), the
        arrival is silently dropped — there is nothing to report.
        """
        candidates = self._usb_discovery.discover_candidates()
        identity_by_path = identity.resolve([candidate.snapshot for candidate in candidates])
        matching_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.snapshot.topology_path == topology_path
            ),
            None,
        )
        if matching_candidate is None:
            return

        self._event_bus.publish(
            SseMessage(
                event=HOTPLUG_DEVICE_ARRIVED_EVENT,
                data=HotplugArrival(
                    event=DeviceArrived(
                        topology_path=topology_path,
                        snapshot=matching_candidate.snapshot,
                        driver_conflict=matching_candidate.driver_conflict,
                    ),
                    identity=identity_by_path.get(topology_path),
                ),
            )
        )

    def is_primary_source_healthy(self) -> bool:
        """Return whether the primary (udev) hotplug source is currently alive.

        False when it degraded to the reconcile-only fallback (architecture
        §4.2 `CompositeHotplugSource`), surfaced as `hotplug.source` /
        `hotplug.healthy` in `GET /api/health`. Duck-typed against
        `degraded_to_reconcile_only` rather than importing
        `CompositeHotplugSource` directly, so this also works against a bare
        `HotplugSource` in tests that never degrades.
        """
        return not getattr(self._hotplug_source, "degraded_to_reconcile_only", False)

    def last_event_at_ms(self) -> int | None:
        """Return the Unix ms timestamp of the most recently observed raw event, if any."""
        return self._last_event_at_ms

    async def close(self) -> None:
        """Stop consuming events and release the underlying hotplug source."""
        pending_tasks = list(self._pending_debounce_tasks.values())
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        self._pending_debounce_tasks.clear()
        self._hotplug_source.close()
