"""Sysfs-sweep `HotplugSource` — the safety net for missed udev events.

Diffs consecutive `UsbDiscovery.enumerate()` snapshots on a fixed interval
and emits `source="reconcile"` events for anything the primary (udev) source
missed, and for the very first snapshot at startup (before any udev event has
ever arrived). Fully testable with `ScriptedUsbDiscovery` + a fake `Clock`
(architecture §4.2, §12.3) — no real filesystem polling loop needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.types import HotplugEvent
from app.backend.interfaces.usb import UsbDiscovery


class ReconcileHotplugSource:
    """A `HotplugSource` that periodically diffs `UsbDiscovery.enumerate()` snapshots.

    Each sweep compares the current set of `topology_path`s against the
    previous sweep's set: newly-present paths emit `action="add"`,
    newly-absent paths emit `action="remove"`. A device that both appears and
    disappears within a single sweep interval produces no event at all — a
    deliberate limitation of any polling-based safety net, expected to be
    covered by the faster udev path in the composite source.
    """

    def __init__(self, discovery: UsbDiscovery, clock: Clock, interval_s: float) -> None:
        """`interval_s` is the sweep period (architecture default 2.0 seconds)."""
        self._discovery = discovery
        self._clock = clock
        self._interval_s = interval_s
        self._closed = False
        self._known_paths: frozenset[str] | None = None

    async def events(self) -> AsyncIterator[HotplugEvent]:
        """Yield `add`/`remove` events for every path that changed since the last sweep.

        The very first sweep is compared against an empty known-set, so a
        device present at startup is reported as `add` — this is what lets
        the reconcile source establish state on process start with no prior
        udev history.
        """
        while not self._closed:
            current_paths = frozenset(
                snapshot.topology_path for snapshot in self._discovery.enumerate()
            )
            previous_paths = self._known_paths or frozenset()
            self._known_paths = current_paths

            observed_at_ms = self._clock.now_ms()
            for added_path in sorted(current_paths - previous_paths):
                yield HotplugEvent(
                    action="add",
                    topology_path=added_path,
                    source="reconcile",
                    observed_at_ms=observed_at_ms,
                )
            for removed_path in sorted(previous_paths - current_paths):
                yield HotplugEvent(
                    action="remove",
                    topology_path=removed_path,
                    source="reconcile",
                    observed_at_ms=observed_at_ms,
                )

            await self._clock.sleep(self._interval_s)

    def close(self) -> None:
        """Stop the sweep loop after its current iteration completes."""
        self._closed = True
