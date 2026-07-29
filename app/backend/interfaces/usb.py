"""USB enumeration and hotplug-notification seams.

`UsbDiscovery` is the synchronous "what is plugged in right now" snapshot;
`HotplugSource` is the asynchronous "something changed" stream. Services
consume both without knowing whether they are backed by real sysfs/udev or a
scripted fixture (architecture §4.1, §4.2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from app.backend.interfaces.types import HotplugEvent, UsbDeviceSnapshot


@runtime_checkable
class UsbDiscovery(Protocol):
    """Produces a point-in-time snapshot of every USB device currently present."""

    def enumerate(self) -> Sequence[UsbDeviceSnapshot]:
        """Return one synchronous, side-effect-free snapshot of present USB devices.

        Implementations must not raise for an individual unreadable device —
        that device is simply omitted from the result (architecture §12.1).
        """
        ...


@runtime_checkable
class HotplugSource(Protocol):
    """A stream of USB add/remove notifications."""

    def events(self) -> AsyncIterator[HotplugEvent]:
        """Yield hotplug events indefinitely until `close()` is called.

        Implementations must never raise out of the async generator for a
        single malformed notification — a bad event is dropped, not fatal.
        """
        ...

    def close(self) -> None:
        """Release any resources (sockets, background tasks) held by this source."""
        ...
