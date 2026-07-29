"""librtlsdr enumeration seam, used to resolve a serial to a spawn-time index.

`rtl_tcp -d <index>` addresses devices by librtlsdr enumeration order, which
is unstable across reboots and replugs (ADR-0003). `supervisor` re-resolves
the index at every spawn via this Protocol; the real adapter binds
`librtlsdr.so.0` through ctypes, the fake lets tests script arbitrary
enumeration orders and duplicate serials.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.backend.interfaces.types import RtlSdrUsbStrings


@runtime_checkable
class RtlSdrLibrary(Protocol):
    """The subset of the librtlsdr C API needed to resolve a spawn index."""

    def device_count(self) -> int:
        """Return the number of RTL-SDR devices librtlsdr currently enumerates.

        Zero while sysfs still shows a device usually means the DVB kernel
        driver is bound instead of the userspace driver (`driver_conflict`).
        """
        ...

    def usb_strings(self, index: int) -> RtlSdrUsbStrings:
        """Return the USB descriptor strings librtlsdr reports for `index`.

        `index` must satisfy `0 <= index < device_count()`. Raises
        `IndexError` (or an adapter-appropriate equivalent) otherwise.
        """
        ...
