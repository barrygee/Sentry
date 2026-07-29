"""Real `HotplugSource` listening on the `udev` netlink multicast group.

Deliberately split so the payload parsing is a pure, fully-testable function
and only the socket `bind`/`recv` loop — a handful of lines with no
conditionals — is untestable without a real Linux kernel (architecture §4.2,
§12.2, §12.9).
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import AsyncIterator

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.types import HotplugEvent

_logger = logging.getLogger(__name__)

# NETLINK_KOBJECT_UEVENT is not exposed by the stdlib `socket` module under a
# named constant; it is a fixed protocol number for the kernel uevent bus.
_NETLINK_KOBJECT_UEVENT = 15
# Group 1 (the "udev" multicast group, as opposed to group 1 which is the raw
# kernel group) is what `udevd` re-broadcasts on after enriching the event
# with the tags/properties Sentry relies on (DEVPATH, ACTION, SUBSYSTEM).
_UDEV_MULTICAST_GROUP = 2
_RECEIVE_BUFFER_SIZE = 16384

_RELEVANT_ACTIONS = frozenset({"add", "remove"})


def parse_uevent(payload: bytes) -> HotplugEvent | None:
    """Parse one raw udev netlink payload into a `HotplugEvent`, or `None`.

    A pure function, deliberately extracted so it is testable against
    captured real payloads without a netlink socket (architecture §12.2).
    Never raises: a truncated, binary, or otherwise unparseable payload
    yields `None` rather than propagating an exception into the socket loop,
    matching `HotplugSource.events()`'s "never raise for one bad notification"
    contract.

    Udev netlink payloads are NUL-separated ASCII/UTF-8 key=value lines,
    prefixed by a header line of the form `"<action>@<devpath>"` which is
    ignored here in favour of the more explicit `ACTION=`/`DEVPATH=`
    key=value pairs that follow it. Only `subsystem=usb` events for a
    *device* `DEVPATH` (not a `:`-suffixed interface path) are ever
    surfaced — everything else (other subsystems, `change`/`bind`/`unbind`
    actions) returns `None`.
    """
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None

    properties: dict[str, str] = {}
    for line in text.split("\x00"):
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key and key not in properties:
            properties[key] = value

    action = properties.get("ACTION")
    subsystem = properties.get("SUBSYSTEM")
    devpath = properties.get("DEVPATH")
    if action not in _RELEVANT_ACTIONS or subsystem != "usb" or not devpath:
        return None

    device_name = devpath.rstrip("/").rsplit("/", 1)[-1]
    if ":" in device_name:
        # An interface node, not a device node — no topology_path to report.
        return None
    if "-" not in device_name:
        # A roothub pseudo-device (e.g. "usb1"), not a physical downstream device.
        return None

    # `observed_at_ms` is not derivable from the payload itself (SEQNUM is a
    # kernel sequence counter, not a timestamp) — the caller stamps it from
    # its injected `Clock` at receipt time; this pure function reports 0 as a
    # placeholder that callers must overwrite.
    return HotplugEvent(
        action="add" if action == "add" else "remove",
        topology_path=device_name,
        source="udev",
        observed_at_ms=0,
    )


class UdevNetlinkHotplugSource:
    """Real `HotplugSource` over an `AF_NETLINK`/`NETLINK_KOBJECT_UEVENT` socket.

    Raises at construction time (rather than on first `events()` call) if the
    netlink socket cannot be created or bound — most commonly because netlink
    is unavailable on this platform (macOS) or the process lacks the
    required privilege — so `CompositeHotplugSource` can catch it immediately
    and degrade to reconcile-only.
    """

    def __init__(self, clock: Clock) -> None:
        """`clock` supplies `observed_at_ms` for each event via `now_ms()`.

        Raises whatever `socket.socket(AF_NETLINK, ...)` raises — typically
        `AttributeError` (no `AF_NETLINK` on this platform, e.g. macOS) or
        `PermissionError`/`OSError` (insufficient privilege) — so
        `CompositeHotplugSource` can catch construction failure and degrade
        to reconcile-only (architecture §4.2).
        """
        self._clock = clock
        # `AF_NETLINK` only exists in the `socket` module's typeshed stub on
        # Linux, so it is looked up dynamically rather than referenced as
        # `socket.AF_NETLINK` directly — this keeps `mypy --strict` clean on
        # every developer platform (including macOS) while still raising a
        # normal `AttributeError` at runtime on a platform without it, which
        # is exactly the "primary unavailable" signal `CompositeHotplugSource`
        # catches and degrades from.
        address_family = getattr(socket, "AF_NETLINK", None)
        if address_family is None:
            raise AttributeError("socket.AF_NETLINK is unavailable on this platform")
        self._socket = socket.socket(address_family, socket.SOCK_DGRAM, _NETLINK_KOBJECT_UEVENT)
        self._socket.bind((0, _UDEV_MULTICAST_GROUP))
        self._socket.setblocking(False)
        self._closed = False

    async def events(self) -> AsyncIterator[HotplugEvent]:
        """Yield parsed hotplug events indefinitely until `close()` is called.

        The `recv`/parse loop itself has no branching logic worth testing
        (architecture §12.9 pragma table) — all decision-making lives in the
        pure `parse_uevent()` above, which is fully covered separately.
        """
        loop = asyncio.get_running_loop()
        while not self._closed:  # pragma: no cover - requires a real netlink socket
            try:
                payload = await loop.sock_recv(self._socket, _RECEIVE_BUFFER_SIZE)
            except OSError:
                if self._closed:
                    return
                _logger.warning("udev netlink socket read failed", exc_info=True)
                continue
            parsed = parse_uevent(payload)
            if parsed is None:
                continue
            yield HotplugEvent(
                action=parsed.action,
                topology_path=parsed.topology_path,
                source="udev",
                observed_at_ms=self._clock.now_ms(),
            )

    def close(self) -> None:
        """Mark the source closed and release the underlying netlink socket."""
        self._closed = True
        self._socket.close()
