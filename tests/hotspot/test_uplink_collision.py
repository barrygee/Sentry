"""Tests for what counts as the host's own uplink on the hotspot's interface.

`uplink_interface_is_hotspot_interface` drives the red "starting the hotspot
will disconnect this link" warning. It used to be computed as

    entry.carries_default_route or entry.active_connection_name is not None

which treated *any* active connection on the radio as an uplink — including
the hotspot's own AP profile. NetworkManager reports that profile as the
interface's active connection while the AP is up, so the warning appeared
because the hotspot had started, telling the operator that starting the
hotspot would disconnect the hotspot. The same profile name was also handed
back as `station_ssid`, so the warning read "this Sentry's own connection to
sentry-hotspot" — naming the network it was itself serving.

These pin the distinction: the hotspot's own profile is not an uplink, any
other active profile is, and a real default route is regardless of which
profile holds it.

Run with:  uv run pytest tests/hotspot
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.dependencies import get_hotspot_service
from app.backend.interfaces.types import (
    HotspotProfile,
    HotspotRuntimeState,
    WirelessInterface,
)
from app.backend.main import create_app
from app.backend.security import require_console_session
from app.backend.services.event_bus import EventBus
from app.backend.services.hotspot import HotspotService
from tests.fakes.clock import FakeClock

HOTSPOT_INTERFACE = "wlan0"
HOTSPOT_CONNECTION_NAME = "sentry-hotspot"
GATEWAY_CIDR = "10.42.0.1/24"
CONFIRM_TIMEOUT_S = 120.0


def _interface(
    *,
    active_connection_name: str | None,
    carries_default_route: bool,
) -> WirelessInterface:
    """The hotspot's radio, varying only the two fields the check reads."""
    return WirelessInterface(
        name=HOTSPOT_INTERFACE,
        mac_address="DC:A6:32:A9:DC:B1",
        supports_ap=True,
        state="connected" if active_connection_name else "disconnected",
        active_connection_name=active_connection_name,
        station_ssid=active_connection_name,
        ipv4_addresses=(),
        carries_default_route=carries_default_route,
    )


class _StubWifiApController:
    """Reports one wireless interface and an active hotspot; mutates nothing."""

    def __init__(self, interface: WirelessInterface) -> None:
        self._interface = interface

    async def is_available(self) -> bool:
        return True

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        return (self._interface,)

    async def read_state(self) -> HotspotRuntimeState:
        return HotspotRuntimeState(
            profile_exists=True,
            active=True,
            autoconnect=False,
            interface=HOTSPOT_INTERFACE,
            ssid="Sentry",
            hidden=False,
            security="wpa2",
            band="bg",
            channel=0,
            gateway_cidr=GATEWAY_CIDR,
            passphrase_set=True,
            activation_state="activated",
        )

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        raise AssertionError("reading a snapshot must not rewrite the profile")

    async def activate(self) -> None:
        raise AssertionError("reading a snapshot must not activate")

    async def deactivate(self) -> None:
        raise AssertionError("reading a snapshot must not deactivate")

    async def set_autoconnect(self, autoconnect: bool) -> None:
        raise AssertionError("reading a snapshot must not change autoconnect")

    async def delete_profile(self) -> None:
        raise AssertionError("reading a snapshot must not delete the profile")

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        raise AssertionError("reading a snapshot must not release a lease")

    async def active_connection_on(self, interface: str) -> str | None:
        return self._interface.active_connection_name

    async def activate_named(self, connection_name: str) -> None:
        raise AssertionError("reading a snapshot must not activate a connection")

    def list_clients(self) -> tuple[()] | None:
        return ()


def _service(interface: WirelessInterface) -> HotspotService:
    clock = FakeClock()
    return HotspotService(
        controller=_StubWifiApController(interface),
        event_bus=EventBus(clock),
        clock=clock,
        default_gateway_cidr=GATEWAY_CIDR,
        confirm_timeout_s=CONFIRM_TIMEOUT_S,
        configured_interface=HOTSPOT_INTERFACE,
        hotspot_connection_name=HOTSPOT_CONNECTION_NAME,
    )


@pytest.mark.asyncio
async def test_the_hotspots_own_profile_is_not_an_uplink() -> None:
    """The regression: the AP being up is not evidence the Pi is connected out."""
    service = _service(
        _interface(
            active_connection_name=HOTSPOT_CONNECTION_NAME,
            carries_default_route=False,
        )
    )

    snapshot = await service.get_snapshot()

    assert snapshot.uplink_interface_is_hotspot_interface is False


@pytest.mark.asyncio
async def test_a_joined_network_on_the_same_radio_is_an_uplink() -> None:
    """A different profile is a real station connection, and must still warn."""
    service = _service(_interface(active_connection_name="house-wifi", carries_default_route=False))

    snapshot = await service.get_snapshot()

    assert snapshot.uplink_interface_is_hotspot_interface is True


@pytest.mark.asyncio
async def test_a_default_route_counts_even_under_the_hotspots_own_profile() -> None:
    """Routing the host's traffic makes it an uplink whatever profile holds it.

    The narrower check must not become "ignore this radio whenever the hotspot
    is on it": an interface carrying the default route is the host's way out by
    definition, and silencing that would hide a genuine lockout.
    """
    service = _service(
        _interface(
            active_connection_name=HOTSPOT_CONNECTION_NAME,
            carries_default_route=True,
        )
    )

    snapshot = await service.get_snapshot()

    assert snapshot.uplink_interface_is_hotspot_interface is True


@pytest.mark.asyncio
async def test_an_idle_radio_is_not_an_uplink() -> None:
    """The baseline: nothing active and no route is nothing to warn about."""
    service = _service(_interface(active_connection_name=None, carries_default_route=False))

    snapshot = await service.get_snapshot()

    assert snapshot.uplink_interface_is_hotspot_interface is False


class _InterfaceListingService:
    """Just enough `HotspotService` for `GET /api/hotspot/interfaces`."""

    def __init__(self, interface: WirelessInterface) -> None:
        self._interface = interface

    @property
    def hotspot_connection_name(self) -> str:
        return HOTSPOT_CONNECTION_NAME

    async def list_interfaces(self) -> tuple[WirelessInterface, ...]:
        return (self._interface,)


def _interfaces_payload(interface: WirelessInterface, tmp_path: Path) -> dict[str, object]:
    """Call the route with the service and console session stubbed out."""
    os.environ["SENTRY_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'interfaces.db'}"
    get_settings.cache_clear()
    try:
        app = create_app()
        app.dependency_overrides[get_hotspot_service] = lambda: _InterfaceListingService(interface)
        app.dependency_overrides[require_console_session] = lambda: None
        with TestClient(app) as client:
            response = client.get("/api/hotspot/interfaces")
        assert response.status_code == 200
        payload: dict[str, object] = response.json()
        return payload
    finally:
        get_settings.cache_clear()


def test_in_use_by_omits_the_hotspots_own_profile(tmp_path: Path) -> None:
    """The console reads a non-null `in_use_by` as "this radio carries a link".

    Reporting our own AP there is what kept the red "starting the hotspot will
    disconnect this link" warning on screen while the hotspot was running.
    """
    payload = _interfaces_payload(
        _interface(active_connection_name=HOTSPOT_CONNECTION_NAME, carries_default_route=False),
        tmp_path,
    )

    entry = payload["interfaces"][0]  # type: ignore[index]
    assert entry["in_use_by"] is None


def test_in_use_by_still_reports_another_connection(tmp_path: Path) -> None:
    """A genuine station connection must still be named, or the warning vanishes."""
    payload = _interfaces_payload(
        _interface(active_connection_name="house-wifi", carries_default_route=False),
        tmp_path,
    )

    entry = payload["interfaces"][0]  # type: ignore[index]
    assert entry["in_use_by"] == "house-wifi"
