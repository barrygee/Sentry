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

    def __init__(
        self, entries: list[RtlSdrUsbStrings] | None = None, available: bool = True
    ) -> None:
        """`entries` is the initial enumeration order; empty models `device_count() == 0`.

        `available=False` models a host with no `librtlsdr` installed at all
        (`main._NullRtlSdrLibrary`'s real-world counterpart) — distinct from
        `available=True` with zero `entries`, which models a loaded library
        that simply enumerates nothing right now. An entry whose
        `manufacturer`/`product`/`serial` are all `""` (e.g.
        `RtlSdrUsbStrings("", "", "")`) models one enumerated-but-unresponsive
        index — the empty-USB-strings signature of a dongle libusb cannot
        actually open (bad cable/power/hub, or a full-speed-only enumeration).
        """
        self.entries: list[RtlSdrUsbStrings] = list(entries) if entries is not None else []
        self.available = available

    def set_entries(self, entries: list[RtlSdrUsbStrings]) -> None:
        """Replace the scripted enumeration order, e.g. to simulate a mid-run replug."""
        self.entries = list(entries)

    def is_available(self) -> bool:
        """Return the scripted `available` flag set at construction."""
        return self.available

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
