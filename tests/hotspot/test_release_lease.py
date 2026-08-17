"""Tests for releasing one DHCP lease.

The lease file under `/var/lib/NetworkManager` is mounted read-only and is
dnsmasq's own state rather than a database: dnsmasq holds leases in memory and
rewrites that file, so deleting a line from it is undone at the next write.
`dhcp_release` is the supported mechanism and the only one that sticks.

Two properties carry the weight here, and both are security-shaped rather than
cosmetic:

* **The address is looked up, never supplied.** A request naming both a MAC and
  an IP would let one client's hardware address be paired with another's
  address, and `dhcp_release` would act on that pair without question.
* **A release is refused unless the hotspot is up.** dnsmasq only exists while
  the shared connection is active, so a release sent to a stopped hotspot has
  nothing listening and fails opaquely rather than saying why.

Run with:  uv run pytest tests/hotspot/test_release_lease.py
"""

from __future__ import annotations

from typing import cast

import pytest

from app.backend.interfaces.types import HotspotClient, HotspotRuntimeState
from app.backend.interfaces.wifi_ap import WifiApController
from app.backend.services.event_bus import EventBus
from app.backend.services.hotspot import HotspotError, HotspotService

from ..fakes.clock import FakeClock

CONNECTION_INTERFACE = "wlan0"
GATEWAY_CIDR = "10.42.0.1/24"
LAPTOP_MAC = "a4:83:e7:9c:1d:02"
LAPTOP_IP = "10.42.0.37"
PHONE_MAC = "b8:27:eb:11:22:33"
PHONE_IP = "10.42.0.42"


def lease(mac_address: str, ip_address: str) -> HotspotClient:
    return HotspotClient(
        mac_address=mac_address,
        ip_address=ip_address,
        hostname=None,
        lease_expires_at_ms=0,
    )


def runtime_state(*, active: bool = True) -> HotspotRuntimeState:
    return HotspotRuntimeState(
        profile_exists=True,
        active=active,
        autoconnect=False,
        interface=CONNECTION_INTERFACE,
        ssid="Sentry",
        hidden=False,
        security="wpa2",
        band="bg",
        channel=0,
        gateway_cidr=GATEWAY_CIDR,
        passphrase_set=True,
        activation_state="activated" if active else None,
    )


class RecordingController:
    """Records the exact `(interface, ip, mac)` triple a release was asked for."""

    def __init__(
        self,
        *,
        active: bool = True,
        clients: tuple[HotspotClient, ...] | None = (),
    ) -> None:
        self._active = active
        self._clients = clients
        self.released: list[tuple[str, str, str]] = []

    async def is_available(self) -> bool:
        return True

    async def read_state(self) -> HotspotRuntimeState:
        return runtime_state(active=self._active)

    def list_clients(self) -> tuple[HotspotClient, ...] | None:
        return self._clients

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        self.released.append((interface, ip_address, mac_address))

    # Nothing else on the protocol is reachable from this path; a call would be
    # a bug, and saying so beats a silent no-op.
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"release_lease must not reach {name}")


def build_service(controller: RecordingController) -> HotspotService:
    clock = FakeClock()
    return HotspotService(
        controller=cast(WifiApController, controller),
        event_bus=EventBus(clock=clock),
        clock=clock,
        default_gateway_cidr=GATEWAY_CIDR,
        confirm_timeout_s=120.0,
        configured_interface=CONNECTION_INTERFACE,
        hotspot_connection_name="sentry-hotspot",
    )


@pytest.mark.asyncio
async def test_releases_the_address_the_lease_list_holds() -> None:
    """The whole point: the IP comes from the server's own records."""
    controller = RecordingController(clients=(lease(LAPTOP_MAC, LAPTOP_IP),))

    await build_service(controller).release_lease(LAPTOP_MAC)

    assert controller.released == [(CONNECTION_INTERFACE, LAPTOP_IP, LAPTOP_MAC)]


@pytest.mark.asyncio
async def test_picks_the_matching_lease_out_of_several() -> None:
    """With more than one client, the wrong pairing is the dangerous outcome."""
    controller = RecordingController(
        clients=(lease(LAPTOP_MAC, LAPTOP_IP), lease(PHONE_MAC, PHONE_IP))
    )

    await build_service(controller).release_lease(PHONE_MAC)

    assert controller.released == [(CONNECTION_INTERFACE, PHONE_IP, PHONE_MAC)]


@pytest.mark.asyncio
async def test_matches_a_mac_whatever_case_it_arrives_in() -> None:
    """Lease files lowercase them; a URL may not. A case mismatch must not 404."""
    controller = RecordingController(clients=(lease(LAPTOP_MAC, LAPTOP_IP),))

    await build_service(controller).release_lease(LAPTOP_MAC.upper())

    assert controller.released == [(CONNECTION_INTERFACE, LAPTOP_IP, LAPTOP_MAC)]


@pytest.mark.asyncio
async def test_refuses_when_the_hotspot_is_not_running() -> None:
    """There is no dnsmasq to talk to, so this must say so rather than fail obscurely."""
    controller = RecordingController(active=False, clients=(lease(LAPTOP_MAC, LAPTOP_IP),))

    with pytest.raises(HotspotError) as raised:
        await build_service(controller).release_lease(LAPTOP_MAC)

    assert raised.value.code == "hotspot_not_running"
    assert controller.released == []


@pytest.mark.asyncio
async def test_refuses_an_unknown_mac_rather_than_guessing() -> None:
    controller = RecordingController(clients=(lease(LAPTOP_MAC, LAPTOP_IP),))

    with pytest.raises(HotspotError) as raised:
        await build_service(controller).release_lease(PHONE_MAC)

    assert raised.value.code == "lease_not_found"
    assert controller.released == []


@pytest.mark.asyncio
async def test_distinguishes_unreadable_leases_from_none() -> None:
    """`None` is "cannot tell", not "nobody is connected".

    Releasing against an unreadable lease list would mean releasing an address
    nothing verified, so it refuses with its own reason rather than reporting
    the lease simply absent.
    """
    controller = RecordingController(clients=None)

    with pytest.raises(HotspotError) as raised:
        await build_service(controller).release_lease(LAPTOP_MAC)

    assert raised.value.code == "leases_unreadable"
    assert controller.released == []
