"""A scriptable `WifiApController` fake for testing the hotspot service.

The real controller talks to NetworkManager over D-Bus and needs a radio, a
Linux host and root. This one holds the same state in memory and records every
mutation, which is what makes the service's genuinely interesting logic —
interface selection, the uplink-loss refusal, and the commit-confirm rollback
timer — exercisable on a laptop with none of those things (ADR-0007).

Follows the idiom `adapters/fake_process.py` established: frozen record types,
a public list of what was called, and scripted failures a test arms in advance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.backend.interfaces.types import (
    HotspotClient,
    HotspotProfile,
    HotspotRuntimeState,
    WirelessInterface,
)
from app.backend.interfaces.wifi_ap import WifiApError


@dataclass(frozen=True, slots=True)
class RecordedApply:
    """One call made to `FakeWifiApController.apply_profile()`, captured for assertions."""

    profile: HotspotProfile
    """The exact profile applied."""

    passphrase: str | None
    """The passphrase passed, or None meaning "leave the stored key alone".

    Captured deliberately: a test must be able to prove that an edit which does
    not change the password sends no passphrase at all, rather than resending
    it or writing back a placeholder.
    """


class FakeWifiApController:
    """An in-memory `WifiApController` whose every answer a test controls."""

    def __init__(
        self,
        *,
        available: bool = True,
        interfaces: tuple[WirelessInterface, ...] = (),
        clients: tuple[HotspotClient, ...] | None = None,
    ) -> None:
        self.available = available
        """Whether `is_available()` answers True.

        Flip it to simulate a host with no NetworkManager."""

        self.interfaces = interfaces
        """The wireless interfaces `list_wireless_interfaces()` reports."""

        self.clients = clients
        """What `list_clients()` returns. `None` means "cannot tell", not "none connected"."""

        self.lease_scopes: list[str | None] = []
        """The `interface` argument of every `list_clients()` call, in order."""

        self.released_leases: list[tuple[str, str, str]] = []
        """Every `(interface, ip_address, mac_address)` passed to `release_lease()`."""

        self.state = HotspotRuntimeState(
            profile_exists=False,
            active=False,
            autoconnect=False,
            interface=None,
            ssid=None,
            hidden=True,
            security="wpa2",
            band="bg",
            channel=0,
            gateway_cidr=None,
            passphrase_set=False,
            activation_state=None,
        )
        """The profile state as this fake currently holds it."""

        self.recorded_applies: list[RecordedApply] = []
        """Every `apply_profile()` call, in order."""

        self.activated_names: list[str] = []
        """Every profile name passed to `activate_named()` — the rollback targets."""

        self.deleted = False
        """True once `delete_profile()` has been called."""

        self.active_connections: dict[str, str] = {}
        """Interface name -> the profile a test says is currently active on it."""

        self._pending_error: WifiApError | None = None

    def raise_on_next(self, error: WifiApError) -> None:
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

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        """Return the scripted interface list."""
        return self.interfaces

    async def read_state(self) -> HotspotRuntimeState:
        """Return the profile state this fake currently holds."""
        return self.state

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        """Record the call and fold the profile into the held state."""
        self._check_pending_error()
        self.recorded_applies.append(RecordedApply(profile=profile, passphrase=passphrase))
        self.state = replace(
            self.state,
            profile_exists=True,
            autoconnect=profile.autoconnect,
            interface=profile.interface,
            ssid=profile.ssid,
            hidden=profile.hidden,
            security=profile.security,
            band=profile.band,
            channel=profile.channel,
            gateway_cidr=profile.gateway_cidr,
            # Once a key is set it stays set; passing None means "unchanged",
            # so it must not clear the flag.
            passphrase_set=self.state.passphrase_set or passphrase is not None,
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
            ssid=None,
            gateway_cidr=None,
            passphrase_set=False,
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
        """Record the release triple, so a test can prove the MAC/IP pairing.

        Was missing entirely, which meant this fake did not actually satisfy
        `WifiApController` — every test using it passed only because nothing had
        yet type-checked the pairing. Added alongside the wired fake's identical
        method (ADR-0014), which is what surfaced the gap.
        """
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
