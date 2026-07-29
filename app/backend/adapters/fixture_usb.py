"""Scriptable `UsbDiscovery` fake for reconcile-sweep and plug/unplug tests.

Returns a different pre-built snapshot on each `enumerate()` call, then
repeats the last one indefinitely, so `ReconcileHotplugSource` (and any other
consumer that polls `enumerate()` on an interval) can be driven through a
scripted sequence of plug/unplug states without touching a filesystem.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.backend.interfaces.types import UsbDeviceSnapshot


class ScriptedUsbDiscovery:
    """Returns each of `snapshots` in turn on successive `enumerate()` calls.

    Once every scripted snapshot has been returned, further calls keep
    returning the last one — this models a device population that has
    settled, so a test does not need to pad the script with repeats of the
    final state.
    """

    def __init__(self, snapshots: Sequence[Sequence[UsbDeviceSnapshot]]) -> None:
        """`snapshots` is the ordered sequence of enumerate() results to replay.

        Raises `ValueError` if empty — there would be nothing to return.
        """
        if not snapshots:
            raise ValueError("ScriptedUsbDiscovery requires at least one snapshot")
        self._snapshots = [list(snapshot) for snapshot in snapshots]
        self._call_count = 0

    @property
    def call_count(self) -> int:
        """The number of times `enumerate()` has been called, for test assertions."""
        return self._call_count

    def enumerate(self) -> list[UsbDeviceSnapshot]:
        """Return the next scripted snapshot, or the last one once exhausted."""
        index = min(self._call_count, len(self._snapshots) - 1)
        self._call_count += 1
        return list(self._snapshots[index])
