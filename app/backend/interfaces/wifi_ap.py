"""Wireless access-point control seam (ADR-0007).

Sentry can raise its own WiFi network so a Sentinel client joins it directly
and reaches the SDRs with no LAN in between. On the target host — Raspberry Pi
OS Bookworm — that means driving NetworkManager, but nothing above this module
knows that: `services/hotspot` sees only this Protocol, so the whole feature is
exercisable against a fake with no radio, no NetworkManager and no root.

Sentry owns exactly **one** connection profile and never reads, edits or
deletes any other. There is deliberately no "list the host's networks" or
"read a stored passphrase" operation here — the absence of those methods is a
security boundary, not an oversight (ADR-0007).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.backend.interfaces.types import (
    HotspotClient,
    HotspotProfile,
    HotspotRuntimeState,
    WirelessInterface,
)


class WifiApError(Exception):
    """Base class for every access-point control failure."""


class WifiApUnavailableError(WifiApError):
    """Access-point control is not possible on this host at all.

    Raised when the control binary is missing or the host runs no
    NetworkManager — the normal state on a developer workstation. Callers
    surface this as a 503 rather than a 500: nothing is broken, the capability
    simply is not there.
    """


class WifiApCommandError(WifiApError):
    """A control command ran and failed.

    `stderr_tail` is already truncated and redacted by the adapter — it may be
    shown to an operator and written to a log, so it must never be the raw
    output (which can echo a property value back, including the passphrase).
    """

    def __init__(self, message: str, *, stderr_tail: str | None, exit_code: int | None) -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail
        self.exit_code = exit_code


class WifiApTimeoutError(WifiApCommandError):
    """A control command did not finish within its timeout and was killed.

    Distinct from a plain failure because an operator's fix differs: a timeout
    usually means the radio or NetworkManager is wedged, not that the request
    was wrong.
    """


@runtime_checkable
class WifiApController(Protocol):
    """Manages the single access-point profile Sentry owns on the host."""

    async def is_available(self) -> bool:
        """Return whether access-point control is possible on this host right now.

        Must never raise — a host with no NetworkManager answers `False`, which
        is what lets `GET /api/hotspot` stay a 200 with `available: false`
        instead of failing.
        """
        ...

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        """Return every wireless interface the host reports.

        Returns an empty tuple rather than raising when nothing can be
        enumerated. The `active_connection_name` and `carries_default_route`
        fields are what the service uses to avoid tearing down the host's own
        uplink.
        """
        ...

    async def read_state(self) -> HotspotRuntimeState:
        """Read back Sentry's profile as NetworkManager currently holds it.

        Never retrieves the stored passphrase — only whether one is set.
        """
        ...

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        """Create or update Sentry's profile to match `profile`.

        `passphrase=None` means **leave the stored key untouched**, which is
        how an operator edits the SSID or channel without re-entering (or the
        server ever re-handling) the secret. Implementations must omit the
        secret entirely from the underlying call in that case rather than
        writing back a placeholder.

        Applying a profile never brings it up; `activate()` does that, so a
        configuration change and a potentially connectivity-breaking activation
        stay separately confirmable.
        """
        ...

    async def activate(self) -> None:
        """Bring Sentry's profile up on its interface."""
        ...

    async def deactivate(self) -> None:
        """Bring Sentry's profile down, leaving it configured."""
        ...

    async def set_autoconnect(self, autoconnect: bool) -> None:
        """Set whether the profile comes up on boot.

        Kept separate from `apply_profile` because it is toggled on its own by
        the commit-confirm flow: the hotspot becomes persistent only once
        someone has proven they can still reach the API with it running.
        """
        ...

    async def delete_profile(self) -> None:
        """Delete Sentry's profile entirely, forgetting the SSID and the stored key."""
        ...

    async def active_connection_on(self, interface: str) -> str | None:
        """Return the name of the profile currently active on `interface`, if any.

        Recorded before an activation so the rollback timer knows what to
        restore if nobody confirms.
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
        """Tell the AP's DHCP server to forget one lease.

        The lease file under `/var/lib/NetworkManager` is mounted read-only and
        is dnsmasq's own state, not a database to edit: dnsmasq keeps leases in
        memory and rewrites that file, so deleting a line from it is undone at
        the next write. `dhcp_release` is the supported way to ask, and the
        only one that actually sticks.

        Forgetting a lease does not disconnect anything. A client still
        associated will simply ask again and may be handed the same address —
        this frees the reservation, it does not evict the device.
        """
        ...

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        """Return the access point's current DHCP leases.

        Synchronous and file-based, mirroring `SocketStatsSource` in
        `interfaces/netprobe.py` — and sharing its contract exactly: `None`
        means **unknown** (no lease file readable: not Linux, no
        NetworkManager, hotspot never enabled), and callers must never render
        it as zero clients. An empty tuple means the file was read and holds no
        leases, which is a genuinely different statement.

        `interface` scopes the read to one interface's lease file. Optional, and
        `None` keeps the original behaviour of merging every lease file on the
        host — but callers that know which interface they mean should say so.
        Once wired sharing can run alongside the hotspot (ADR-0014) there are
        two shared connections writing two lease files, and an unscoped read
        would list a cabled laptop as a WiFi client.
        """
        ...
