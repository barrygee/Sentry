"""Wired (Ethernet) connection-sharing seam (ADR-0014).

Sentry can serve DHCP on one of the Pi's Ethernet ports, so a laptop plugged
straight into it gets an address and reaches Sentry and Sentinel exactly as it
would over the hotspot — no router, no switch, no LAN in between. On the target
host that means driving NetworkManager's `ipv4.method shared`, but nothing above
this module knows that: `services/wired_share` sees only this Protocol, so the
whole feature is exercisable on a laptop with no NetworkManager and no root.

**This is the WiFi hotspot's twin, not its generalisation.** The two seams are
deliberately separate Protocols rather than one with nullable radio fields:
there is no SSID, no band, no channel and — the difference that matters — *no
passphrase*. A wired share's credential is the cable, so there is no secret to
keep write-only anywhere in this feature, and no method here that could leak
one. Folding the two together would have meant a controller whose secret
handling was conditional, which is the last place conditional secret handling
belongs.

Sentry owns exactly **one** wired profile and never reads, edits or deletes any
other — the same ownership rule ADR-0007 set for the hotspot, and for the same
reason: an operator's own `eth0` connection is not Sentry's to rewrite.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.backend.interfaces.types import (
    HotspotClient,
    WiredInterface,
    WiredShareProfile,
    WiredShareRuntimeState,
)


class WiredShareError(Exception):
    """Base class for every wired-sharing control failure."""


class WiredShareUnavailableError(WiredShareError):
    """Wired-sharing control is not possible on this host at all.

    Raised when `nmcli` is missing or the host runs no NetworkManager — the
    normal state on a developer workstation. Callers surface this as a 503
    rather than a 500: nothing is broken, the capability simply is not there.
    """


class WiredShareCommandError(WiredShareError):
    """A control command ran and failed.

    `stderr_tail` is already truncated by the adapter — it may be shown to an
    operator and written to a log. Unlike the hotspot's equivalent it needs no
    redaction, because no wired-sharing command ever carries a secret for nmcli
    to echo back.
    """

    def __init__(self, message: str, *, stderr_tail: str | None, exit_code: int | None) -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail
        self.exit_code = exit_code


class WiredShareTimeoutError(WiredShareCommandError):
    """A control command did not finish within its timeout and was killed.

    Distinct from a plain failure because an operator's fix differs: a timeout
    usually means NetworkManager is wedged, not that the request was wrong.
    """


@runtime_checkable
class WiredShareController(Protocol):
    """Manages the single wired-sharing profile Sentry owns on the host."""

    async def is_available(self) -> bool:
        """Return whether wired-sharing control is possible on this host right now.

        Must never raise — a host with no NetworkManager answers `False`, which
        is what lets `GET /api/wired` stay a 200 with `available: false` instead
        of failing.
        """
        ...

    async def list_wired_interfaces(self) -> tuple[WiredInterface, ...]:
        """Return every Ethernet interface the host reports.

        Returns an empty tuple rather than raising when nothing can be
        enumerated. `active_connection_name`, `carries_default_route` and
        `carrier_up` are what the service uses to avoid tearing down the host's
        own uplink unasked, and to explain an empty client list.
        """
        ...

    async def read_state(self) -> WiredShareRuntimeState:
        """Read back Sentry's wired profile as NetworkManager currently holds it."""
        ...

    async def apply_profile(self, profile: WiredShareProfile) -> None:
        """Create or update Sentry's wired profile to match `profile`.

        Takes no secret, because there is none — see the module docstring.

        Applying a profile never brings it up; `activate()` does that, so a
        configuration change and a potentially connectivity-breaking activation
        stay separately confirmable.
        """
        ...

    async def activate(self) -> None:
        """Bring Sentry's wired profile up on its interface."""
        ...

    async def deactivate(self) -> None:
        """Bring Sentry's wired profile down, leaving it configured."""
        ...

    async def set_autoconnect(self, autoconnect: bool) -> None:
        """Set whether the profile comes up on boot.

        Kept separate from `apply_profile` because the commit-confirm flow
        toggles it on its own: sharing becomes persistent only once someone has
        proven they can still reach the API with it running.
        """
        ...

    async def delete_profile(self) -> None:
        """Delete Sentry's wired profile entirely."""
        ...

    async def active_connection_on(self, interface: str) -> str | None:
        """Return the name of the profile currently active on `interface`, if any.

        Recorded before an activation so the rollback timer knows what to
        restore if nobody confirms. On the target Pi this is normally the
        profile carrying the Pi's own LAN connection, which is exactly what a
        rollback has to put back.
        """
        ...

    async def activate_named(self, connection_name: str) -> None:
        """Bring an arbitrary, previously-recorded profile back up.

        The rollback target. This is the one operation that touches a profile
        Sentry does not own, and only ever with a name it observed itself
        moments earlier — never one supplied by a request.
        """
        ...

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        """Tell the shared connection's DHCP server to forget one lease.

        Forgetting a lease does not unplug anything. A machine still cabled in
        will simply ask again and may be handed the same address — this frees
        the reservation, it does not disconnect the device.
        """
        ...

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        """Return the shared connection's current DHCP leases.

        Synchronous and file-based, sharing `SocketStatsSource`'s contract
        exactly: `None` means **unknown** (no lease file readable), and callers
        must never render it as zero clients. An empty tuple means the file was
        read and holds no leases, which is a genuinely different statement.

        `interface` scopes the read to one port's lease file. That scoping is
        what keeps the hotspot's clients and the wired share's clients apart
        when both are running at once — NetworkManager writes one lease file per
        interface, and merging them would list a laptop on the cable as a WiFi
        client and vice versa.
        """
        ...
