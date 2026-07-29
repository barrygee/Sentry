"""Scriptable `RtlSdrLibrary` fake — enumeration order, duplicates, reordering.

Lets `services.supervisor`'s spawn-index resolution (ADR-0003 §5.3) be tested
against every failure mode: no match, exactly one match, and duplicate
serials producing an ambiguous match — none of which require real hardware
or `librtlsdr` to be installed.
"""

from __future__ import annotations

from app.backend.interfaces.types import RtlSdrUsbStrings


class FakeRtlSdrLibrary:
    """An `RtlSdrLibrary` whose enumeration order is set (and can be reset) by the test.

    `entries[i]` is what `usb_strings(i)` returns — including duplicate
    `RtlSdrUsbStrings` at different indices, to drive the `ambiguous_index`
    path exactly as real duplicate-serial hardware would.
    """

    def __init__(self, entries: list[RtlSdrUsbStrings] | None = None) -> None:
        """`entries` is the initial enumeration order; empty models `device_count() == 0`."""
        self.entries: list[RtlSdrUsbStrings] = list(entries) if entries is not None else []

    def set_entries(self, entries: list[RtlSdrUsbStrings]) -> None:
        """Replace the scripted enumeration order, e.g. to simulate a mid-run replug."""
        self.entries = list(entries)

    def device_count(self) -> int:
        """Return the number of scripted entries."""
        return len(self.entries)

    def usb_strings(self, index: int) -> RtlSdrUsbStrings:
        """Return the scripted entry at `index`.

        Raises `IndexError` for any index outside `[0, device_count())`,
        matching the real adapter's contract.
        """
        if index < 0 or index >= len(self.entries):
            raise IndexError(f"FakeRtlSdrLibrary has no entry at index {index}")
        return self.entries[index]
