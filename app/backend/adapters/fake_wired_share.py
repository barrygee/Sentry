"""A scriptable `WiredShareController` fake for testing the wired-sharing service.

The real controller talks to NetworkManager over D-Bus and needs a Linux host
and root. This one holds the same state in memory and records every mutation,
which is what makes the service's genuinely interesting logic — port selection,
the uplink-loss refusal, and the commit-confirm rollback timer — exercisable on
a laptop with none of those things (ADR-0014).

The wired twin of `fake_wifi_ap.py`, following the same idiom: frozen record
types, a public list of what was called, and scripted failures a test arms in
advance. It is deliberately simpler in exactly one way — `apply_profile()` takes
no passphrase, because there is no secret in this feature to capture.
"""

from __future__ import annotations

from dataclasses import replace

from app.backend.interfaces.types import (
    HotspotClient,
    WiredInterface,
    WiredShareProfile,
    WiredShareRuntimeState,
)
from app.backend.interfaces.wired_share import WiredShareError


class FakeWiredShareController:
    """An in-memory `WiredShareController` whose every answer a test controls."""

    def __init__(
        self,
        *,
        available: bool = True,
        interfaces: tuple[WiredInterface, ...] = (),
        clients: tuple[HotspotClient, ...] | None = None,
    ) -> None:
        self.available = available
        """Whether `is_available()` answers True.

        Flip it to simulate a host with no NetworkManager."""

        self.interfaces = interfaces
        """The Ethernet ports `list_wired_interfaces()` reports."""

        self.clients = clients
        """What `list_clients()` returns. `None` means "cannot tell", not "none plugged in"."""

        self.lease_scopes: list[str | None] = []
        """The `interface` argument of every `list_clients()` call, in order."""

        self.released_leases: list[tuple[str, str, str]] = []
        """Every `(interface, ip_address, mac_address)` passed to `release_lease()`."""

        self.state = WiredShareRuntimeState(
            profile_exists=False,
            active=False,
            autoconnect=False,
            interface=None,
            gateway_cidr=None,
            activation_state=None,
        )
        """The profile state as this fake currently holds it."""

        self.recorded_applies: list[WiredShareProfile] = []
        """Every profile passed to `apply_profile()`, in order.

        A bare list of profiles rather than a `RecordedApply` wrapper: the
        hotspot's equivalent exists only to capture the passphrase alongside the
        profile, and there is no passphrase here to capture.
        """

        self.activated_names: list[str] = []
        """Every profile name passed to `activate_named()` — the rollback targets."""

        self.deleted = False
        """True once `delete_profile()` has been called."""

        self.active_connections: dict[str, str] = {}
        """Interface name -> the profile a test says is currently active on it."""

        self._pending_error: WiredShareError | None = None

    def raise_on_next(self, error: WiredShareError) -> None:
        """Arm the next mutating call to raise `error`, then disarm.

        One-shot rather than sticky so a test can script "the activation fails,
        the rollback that follows succeeds" — which is the path that matters.
        """
        self._pending_error = error

    def _check_pending_error(self) -> None:
        """Raise and clear any armed error."""
        error = self._pending_error
        if error is not None:
            self._pending_error = None
            raise error

    async def is_available(self) -> bool:
        """Return the scripted availability."""
        return self.available

    async def list_wired_interfaces(self) -> tuple[WiredInterface, ...]:
        """Return the scripted port list."""
        return self.interfaces

    async def read_state(self) -> WiredShareRuntimeState:
        """Return the profile state this fake currently holds."""
        return self.state

    async def apply_profile(self, profile: WiredShareProfile) -> None:
        """Record the call and fold the profile into the held state."""
        self._check_pending_error()
        self.recorded_applies.append(profile)
        self.state = replace(
            self.state,
            profile_exists=True,
            autoconnect=profile.autoconnect,
            interface=profile.interface,
            gateway_cidr=profile.gateway_cidr,
        )

    async def activate(self) -> None:
        """Mark the profile active."""
        self._check_pending_error()
        self.state = replace(self.state, active=True, activation_state="activated")

    async def deactivate(self) -> None:
        """Mark the profile inactive."""
        self._check_pending_error()
        self.state = replace(self.state, active=False, activation_state="deactivated")

    async def set_autoconnect(self, autoconnect: bool) -> None:
        """Set the held autoconnect flag."""
        self._check_pending_error()
        self.state = replace(self.state, autoconnect=autoconnect)

    async def delete_profile(self) -> None:
        """Forget the profile entirely."""
        self._check_pending_error()
        self.deleted = True
        self.state = replace(
            self.state,
            profile_exists=False,
            active=False,
            autoconnect=False,
            interface=None,
            gateway_cidr=None,
            activation_state=None,
        )

    async def active_connection_on(self, interface: str) -> str | None:
        """Return whatever a test said is active on `interface`."""
        return self.active_connections.get(interface)

    async def activate_named(self, connection_name: str) -> None:
        """Record a rollback activation."""
        self._check_pending_error()
        self.activated_names.append(connection_name)

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        """Record the release triple, so a test can prove the MAC/IP pairing."""
        self._check_pending_error()
        self.released_leases.append((interface, ip_address, mac_address))

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        """Return the scripted lease list, recording the interface it was scoped to.

        The scope is recorded rather than applied: a fake that filtered its own
        scripted list would be testing this method's filter instead of the
        caller's decision about which interface to ask for, which is the part
        that can actually be wrong.
        """
        self.lease_scopes.append(interface)
        return self.clients
