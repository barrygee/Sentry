"""Tests that each shared network reports only its own DHCP leases.

NetworkManager writes one dnsmasq lease file per interface
(`dnsmasq-wlan0.leases`, `dnsmasq-eth0.leases`), and `read_dnsmasq_leases` used
to glob all of them and merge the results. That was correct while the hotspot
was the only thing on the host that could raise a `shared` connection.

Wired sharing (ADR-0014) makes it wrong: with both up, the hotspot's panel would
list the laptop on the Ethernet cable among its WiFi clients, and the wired panel
would list every phone on the hotspot. Worse than cosmetic — the release control
beside each row sends a `dhcp_release` to the *wrong* dnsmasq.

So the read is now scoped by interface, and each service passes its own
profile's. These pin both halves: the parser honours the scope, and the services
supply it.

Run with:  uv run pytest tests/hotspot/test_lease_scoping.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.backend.adapters.fake_wifi_ap import FakeWifiApController
from app.backend.adapters.fake_wired_share import FakeWiredShareController
from app.backend.adapters.nmcli_parsing import read_dnsmasq_leases
from app.backend.interfaces.types import HotspotRuntimeState, WiredShareRuntimeState
from app.backend.services.event_bus import EventBus
from app.backend.services.hotspot import HotspotService
from app.backend.services.wired_share import WiredShareService
from tests.fakes.clock import FakeClock

HOTSPOT_LEASE = "4000000000 aa:bb:cc:dd:ee:01 10.42.0.50 phone *\n"
WIRED_LEASE = "4000000000 aa:bb:cc:dd:ee:02 10.10.10.50 laptop *\n"


@pytest.fixture
def lease_root(tmp_path: Path) -> Path:
    """A NetworkManager state directory with one lease file per interface."""
    (tmp_path / "dnsmasq-wlan0.leases").write_text(HOTSPOT_LEASE, encoding="utf-8")
    (tmp_path / "dnsmasq-eth0.leases").write_text(WIRED_LEASE, encoding="utf-8")
    return tmp_path


class TestTheParserHonoursTheScope:
    """`read_dnsmasq_leases` against a real fixture tree, no NetworkManager involved."""

    def test_a_named_interface_reads_only_its_own_file(self, lease_root: Path) -> None:
        hotspot_clients = read_dnsmasq_leases(lease_root, "wlan0")
        wired_clients = read_dnsmasq_leases(lease_root, "eth0")

        assert hotspot_clients is not None and wired_clients is not None
        assert [entry.ip_address for entry in hotspot_clients] == ["10.42.0.50"]
        assert [entry.ip_address for entry in wired_clients] == ["10.10.10.50"]

    def test_no_interface_still_merges_every_file(self, lease_root: Path) -> None:
        """The original behaviour is kept for callers that genuinely do not know."""
        clients = read_dnsmasq_leases(lease_root)

        assert clients is not None
        assert sorted(entry.ip_address for entry in clients) == ["10.10.10.50", "10.42.0.50"]

    def test_an_interface_with_no_lease_file_is_unknown_not_empty(self, lease_root: Path) -> None:
        """`None` and `[]` are different answers; a wrong guess must not read as zero."""
        assert read_dnsmasq_leases(lease_root, "eth9") is None

    def test_a_missing_state_root_is_unknown(self, tmp_path: Path) -> None:
        assert read_dnsmasq_leases(tmp_path / "nope", "eth0") is None


class TestTheHotspotServiceSuppliesItsInterface:
    """The regression: the hotspot must ask for its own radio, not for everything."""

    @pytest.mark.asyncio
    async def test_leases_are_scoped_to_the_profiles_interface(self) -> None:
        controller = FakeWifiApController(clients=())
        controller.state = HotspotRuntimeState(
            profile_exists=True,
            active=True,
            autoconnect=False,
            interface="wlan0",
            ssid="Sentry",
            hidden=True,
            security="wpa2",
            band="bg",
            channel=0,
            gateway_cidr="10.42.0.1/24",
            passphrase_set=True,
            activation_state="activated",
        )
        service = _hotspot_service(controller)

        await service.list_clients()

        assert controller.lease_scopes == ["wlan0"]

    @pytest.mark.asyncio
    async def test_an_unconfigured_hotspot_reports_unknown_rather_than_borrowing(self) -> None:
        """With no interface there are no leases of ours — never another's."""
        controller = FakeWifiApController(clients=())
        service = _hotspot_service(controller)

        assert await service.list_clients() is None


class TestBothServicesStayApart:
    """End to end over one fixture tree: neither service sees the other's clients."""

    @pytest.mark.asyncio
    async def test_each_service_sees_only_its_own_lease(self, lease_root: Path) -> None:
        from app.backend.adapters.nmcli_wifi_ap import UnavailableWifiApController
        from app.backend.adapters.nmcli_wired_share import UnavailableWiredShareController

        # The unavailable controllers still read leases — a plain file read needs
        # no NetworkManager — which is exactly what makes this assertable here.
        hotspot_clients = UnavailableWifiApController("no nmcli", lease_root).list_clients("wlan0")
        wired_clients = UnavailableWiredShareController("no nmcli", lease_root).list_clients("eth0")

        assert hotspot_clients is not None and wired_clients is not None
        assert [entry.hostname for entry in hotspot_clients] == ["phone"]
        assert [entry.hostname for entry in wired_clients] == ["laptop"]

    @pytest.mark.asyncio
    async def test_the_wired_service_supplies_its_own_interface(self) -> None:
        controller = FakeWiredShareController(clients=())
        controller.state = WiredShareRuntimeState(
            profile_exists=True,
            active=True,
            autoconnect=False,
            interface="eth0",
            gateway_cidr="10.10.10.1/24",
            activation_state="activated",
        )
        service = _wired_service(controller)

        await service.list_clients()

        assert controller.lease_scopes == ["eth0"]


def _hotspot_service(controller: FakeWifiApController) -> HotspotService:
    clock = FakeClock()
    return HotspotService(
        controller=controller,
        event_bus=EventBus(clock),
        clock=clock,
        default_gateway_cidr="10.42.0.1/24",
        confirm_timeout_s=120.0,
        configured_interface=None,
        hotspot_connection_name="sentry-hotspot",
    )


def _wired_service(controller: FakeWiredShareController) -> WiredShareService:
    clock = FakeClock()
    return WiredShareService(
        controller=controller,
        event_bus=EventBus(clock),
        clock=clock,
        default_gateway_cidr="10.10.10.1/24",
        confirm_timeout_s=120.0,
        configured_interface=None,
        wired_connection_name="sentry-wired",
    )
