"""Tests for `HotspotService.enable()` refusing a profile that has no passphrase.

Saving a hotspot has always refused this combination (`apply_configuration`
raises `passphrase_required` when no key is supplied and none is stored), but
`enable()` checked only that a profile *existed*. A profile can reach that
state legitimately — a config import writes settings without a key, or an
operator creates one with `nmcli` on the Pi — and enabling it then handed
NetworkManager a WPA profile with no PSK, which fails deep inside activation
and surfaces as an opaque command error rather than the one actionable fact.

Both supported security types (`wpa2`, `wpa3`) are keyed, so there is no open
network for which a missing passphrase would be legitimate; the guard is
unconditional and these tests pin it that way.

Run with:  uv run pytest tests/hotspot
"""

from __future__ import annotations

import pytest

from app.backend.interfaces.types import (
    HotspotProfile,
    HotspotRuntimeState,
    WirelessInterface,
)
from app.backend.services.event_bus import EventBus
from app.backend.services.hotspot import HotspotError, HotspotService
from tests.fakes.clock import FakeClock

HOTSPOT_INTERFACE = "wlan0"
GATEWAY_CIDR = "10.42.0.1/24"
CONFIRM_TIMEOUT_S = 120.0


def _runtime_state(*, profile_exists: bool = True, passphrase_set: bool) -> HotspotRuntimeState:
    """A configured, inactive profile, varying only the two fields under test."""
    return HotspotRuntimeState(
        profile_exists=profile_exists,
        active=False,
        autoconnect=False,
        interface=HOTSPOT_INTERFACE,
        ssid="Sentry",
        hidden=False,
        security="wpa2",
        band="bg",
        channel=0,
        gateway_cidr=GATEWAY_CIDR,
        passphrase_set=passphrase_set,
        activation_state=None,
    )


class _RecordingWifiApController:
    """A `WifiApController` double that records activation without touching a radio.

    `activate` and `set_autoconnect` are the two calls that would put a network
    on the air, so both are recorded — asserting the guard fired means asserting
    neither ran.
    """

    def __init__(self, *, passphrase_set: bool, profile_exists: bool = True) -> None:
        self._state = _runtime_state(profile_exists=profile_exists, passphrase_set=passphrase_set)
        self.activate_calls = 0
        self.autoconnect_calls: list[bool] = []

    async def is_available(self) -> bool:
        return True

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        # Idle and carrying no route, so interface selection cannot be what
        # refuses — any refusal in these tests is the passphrase guard.
        return (
            WirelessInterface(
                name=HOTSPOT_INTERFACE,
                mac_address="DC:A6:32:A9:DC:B1",
                supports_ap=True,
                state="disconnected",
                active_connection_name=None,
                station_ssid=None,
                ipv4_addresses=(),
                carries_default_route=False,
            ),
        )

    async def read_state(self) -> HotspotRuntimeState:
        return self._state

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        raise AssertionError("enable() must not rewrite the profile")

    async def activate(self) -> None:
        self.activate_calls += 1

    async def deactivate(self) -> None:
        pass

    async def set_autoconnect(self, autoconnect: bool) -> None:
        self.autoconnect_calls.append(autoconnect)

    async def delete_profile(self) -> None:
        raise AssertionError("enable() must not delete the profile")

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        raise AssertionError("enable() must not release a lease")

    async def active_connection_on(self, interface: str) -> str | None:
        return None

    async def activate_named(self, connection_name: str) -> None:
        pass

    def list_clients(self) -> tuple[()] | None:
        return ()


def _service(controller: _RecordingWifiApController) -> HotspotService:
    clock = FakeClock()
    return HotspotService(
        controller=controller,
        event_bus=EventBus(clock),
        clock=clock,
        default_gateway_cidr=GATEWAY_CIDR,
        confirm_timeout_s=CONFIRM_TIMEOUT_S,
        configured_interface=HOTSPOT_INTERFACE,
        hotspot_connection_name="sentry-hotspot",
    )


@pytest.mark.asyncio
async def test_enabling_without_a_stored_passphrase_is_refused() -> None:
    """The guard itself: a keyed profile with no key cannot be raised."""
    controller = _RecordingWifiApController(passphrase_set=False)

    with pytest.raises(HotspotError) as raised:
        await _service(controller).enable(confirm_uplink_loss=False)

    assert raised.value.code == "passphrase_required"
    assert raised.value.context["reason"] == "no_stored_passphrase"


@pytest.mark.asyncio
async def test_the_refusal_names_the_thing_to_fix() -> None:
    """The message is the whole point of the change — it must be actionable.

    An operator reading "the network command failed" has nowhere to go; this
    sentence tells them exactly what is missing.
    """
    controller = _RecordingWifiApController(passphrase_set=False)

    with pytest.raises(HotspotError) as raised:
        await _service(controller).enable(confirm_uplink_loss=False)

    assert raised.value.message == "Set a password for the hotspot before enabling it."


@pytest.mark.asyncio
async def test_nothing_is_put_on_the_air_when_the_guard_refuses() -> None:
    """Refusing late — after activation — would broadcast a half-formed network.

    The guard runs before `_activate_provisionally`, so neither the activation
    nor the autoconnect that follows it may have happened.
    """
    controller = _RecordingWifiApController(passphrase_set=False)

    with pytest.raises(HotspotError):
        await _service(controller).enable(confirm_uplink_loss=False)

    assert controller.activate_calls == 0
    assert controller.autoconnect_calls == []


@pytest.mark.asyncio
async def test_a_missing_profile_still_refuses_as_unconfigured() -> None:
    """Ordering: `_require_configured` must keep precedence over the new guard.

    A host with no profile at all has nothing to set a password *on*, so
    "configure it first" is the truthful error — telling that operator to set a
    passphrase would send them looking for a form that is not there.
    """
    controller = _RecordingWifiApController(passphrase_set=False, profile_exists=False)

    with pytest.raises(HotspotError) as raised:
        await _service(controller).enable(confirm_uplink_loss=False)

    assert raised.value.code == "hotspot_not_configured"


@pytest.mark.asyncio
async def test_a_profile_with_a_passphrase_still_enables() -> None:
    """The negative case's counterpart: the guard must not block the normal path.

    Without this, a guard that always raised would pass every test above.
    """
    controller = _RecordingWifiApController(passphrase_set=True)

    snapshot = await _service(controller).enable(confirm_uplink_loss=False)

    assert controller.activate_calls == 1
    assert snapshot.state.passphrase_set is True
