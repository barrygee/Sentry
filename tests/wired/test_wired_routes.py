"""Tests for `/api/wired*` — the two gates, and the degradation contract.

Two things are worth pinning at the route layer rather than the service layer,
because only the routes decide them:

1. **Reads never fail.** A host with no NetworkManager answers 200 with
   `available: false` and a warning, so the console can always render something
   truthful. A 503 here would leave the UI unable to explain itself.
2. **Every mutation is gated twice** — host-network control switched on, and a
   console password set — and the gates are checked in the order an operator
   should fix them, so the first error names the first thing to do.

Both gates deliberately reuse the hotspot's: one host-network capability,
granted once (ADR-0014).

Run with:  uv run pytest tests/wired
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.dependencies import (
    get_console_auth_service,
    get_host_control_settings,
    get_wired_share_service,
)
from app.backend.interfaces.types import HotspotClient, WiredInterface, WiredShareRuntimeState
from app.backend.main import create_app
from app.backend.security import require_console_session
from app.backend.services.wired_share import WiredError, WiredShareSnapshot

WIRED_CONNECTION_NAME = "sentry-wired"
GATEWAY_CIDR = "10.10.10.1/24"


def _runtime_state(
    *,
    profile_exists: bool = True,
    active: bool = True,
    interface: str | None = "eth0",
) -> WiredShareRuntimeState:
    return WiredShareRuntimeState(
        profile_exists=profile_exists,
        active=active,
        autoconnect=False,
        interface=interface,
        gateway_cidr=GATEWAY_CIDR if profile_exists else None,
        activation_state="activated" if active else None,
    )


def _snapshot(
    *,
    available: bool = True,
    state: WiredShareRuntimeState | None = None,
    uplink_collision: bool = False,
    carrier_up: bool | None = True,
) -> WiredShareSnapshot:
    return WiredShareSnapshot(
        available=available,
        state=state or _runtime_state(),
        uplink_interface_is_share_interface=uplink_collision,
        carrier_up=carrier_up,
        pending_confirmation=False,
        confirm_deadline_ms=None,
        last_error=None,
    )


class _StubWiredService:
    """Just enough `WiredShareService` for the routes, recording what they call."""

    def __init__(
        self,
        *,
        snapshot: WiredShareSnapshot | None = None,
        interfaces: tuple[WiredInterface, ...] = (),
        clients: tuple[HotspotClient, ...] | None = None,
        error: WiredError | None = None,
    ) -> None:
        self._snapshot = snapshot or _snapshot()
        self._interfaces = interfaces
        self._clients = clients
        self._error = error
        self.mutations: list[str] = []
        """Every mutating method the routes reached, so a blocked call is provable."""

    @property
    def wired_connection_name(self) -> str:
        return WIRED_CONNECTION_NAME

    async def get_snapshot(self) -> WiredShareSnapshot:
        return self._snapshot

    async def list_interfaces(self) -> tuple[WiredInterface, ...]:
        return self._interfaces

    async def list_clients(self) -> tuple[HotspotClient, ...] | None:
        return self._clients

    def _act(self, name: str) -> WiredShareSnapshot:
        self.mutations.append(name)
        if self._error is not None:
            raise self._error
        return self._snapshot

    async def apply_configuration(self, **_kwargs: object) -> WiredShareSnapshot:
        return self._act("apply_configuration")

    async def enable(self, _confirm: bool) -> WiredShareSnapshot:
        return self._act("enable")

    async def disable(self, _confirm: bool) -> WiredShareSnapshot:
        return self._act("disable")

    async def confirm(self) -> WiredShareSnapshot:
        return self._act("confirm")

    async def forget(self) -> None:
        self._act("forget")

    async def release_lease(self, _mac_address: str) -> None:
        self._act("release_lease")


class _StubConsoleAuth:
    def __init__(self, *, password_set: bool) -> None:
        self._password_set = password_set

    async def is_password_set(self) -> bool:
        return self._password_set


class _StubHostControl:
    def __init__(self, *, control_enabled: bool) -> None:
        self._control_enabled = control_enabled

    async def hotspot_control_enabled(self) -> bool:
        return self._control_enabled


def _client(
    tmp_path: Path,
    service: _StubWiredService,
    *,
    control_enabled: bool = True,
    password_set: bool = True,
    advertised_host: str | None = None,
) -> Iterator[TestClient]:
    """Build an app with the wired service, auth and host control all stubbed."""
    os.environ["SENTRY_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'wired.db'}"
    if advertised_host is None:
        os.environ.pop("SENTRY_ADVERTISED_HOST", None)
    else:
        os.environ["SENTRY_ADVERTISED_HOST"] = advertised_host
    get_settings.cache_clear()
    try:
        app = create_app()
        app.dependency_overrides[get_wired_share_service] = lambda: service
        app.dependency_overrides[get_console_auth_service] = lambda: _StubConsoleAuth(
            password_set=password_set
        )
        app.dependency_overrides[get_host_control_settings] = lambda: _StubHostControl(
            control_enabled=control_enabled
        )
        app.dependency_overrides[require_console_session] = lambda: None
        with TestClient(app) as client:
            yield client
    finally:
        os.environ.pop("SENTRY_ADVERTISED_HOST", None)
        get_settings.cache_clear()


MUTATIONS: list[tuple[str, str, dict[str, object] | None]] = [
    ("put", "/api/wired", {"enabled": True}),
    ("post", "/api/wired/enable", {}),
    ("post", "/api/wired/disable", {}),
    ("post", "/api/wired/confirm", None),
    ("delete", "/api/wired", None),
    ("delete", "/api/wired/clients/aa:bb:cc:dd:ee:ff", None),
]
"""Every mutating route, so a gate that is added to some but not all is caught."""


class TestReadsNeverFail:
    """A read has to work in order to tell an operator why nothing else does."""

    def test_state_is_200_even_with_no_networkmanager(self, tmp_path: Path) -> None:
        service = _StubWiredService(snapshot=_snapshot(available=False))
        for client in _client(tmp_path, service):
            response = client.get("/api/wired")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert "nm_unavailable" in body["warnings"]

    def test_state_is_readable_with_control_switched_off(self, tmp_path: Path) -> None:
        """The one route that must answer when every other one is refused."""
        service = _StubWiredService()
        for client in _client(tmp_path, service, control_enabled=False):
            response = client.get("/api/wired")

        assert response.status_code == 200
        assert response.json()["control_enabled"] is False

    def test_the_gateway_address_is_split_out_of_the_cidr(self, tmp_path: Path) -> None:
        """The address a human types into Sentinel, without its prefix length."""
        service = _StubWiredService()
        for client in _client(tmp_path, service):
            body = client.get("/api/wired").json()

        assert body["gateway_address"] == "10.10.10.1"
        assert body["gateway_cidr"] == GATEWAY_CIDR


class TestWarnings:
    """Non-fatal conditions the console renders. Warnings never block a read."""

    def test_a_missing_console_password_warns(self, tmp_path: Path) -> None:
        service = _StubWiredService()
        for client in _client(tmp_path, service, password_set=False):
            body = client.get("/api/wired").json()

        assert "console_password_missing" in body["warnings"]

    def test_sharing_the_uplink_port_warns(self, tmp_path: Path) -> None:
        service = _StubWiredService(snapshot=_snapshot(uplink_collision=True))
        for client in _client(tmp_path, service):
            body = client.get("/api/wired").json()

        assert "shares_uplink_port" in body["warnings"]

    def test_an_unplugged_cable_warns_only_once_sharing_is_running(self, tmp_path: Path) -> None:
        """Nothing plugged into a share nobody started is expected, not a problem."""
        stopped = _StubWiredService(
            snapshot=_snapshot(state=_runtime_state(active=False), carrier_up=False)
        )
        for client in _client(tmp_path, stopped):
            stopped_body = client.get("/api/wired").json()

        running = _StubWiredService(snapshot=_snapshot(carrier_up=False))
        for client in _client(tmp_path, running):
            running_body = client.get("/api/wired").json()

        assert "no_carrier" not in stopped_body["warnings"]
        assert "no_carrier" in running_body["warnings"]

    def test_an_unknown_carrier_never_warns(self, tmp_path: Path) -> None:
        """`None` is "the host did not say", which is not evidence of anything."""
        service = _StubWiredService(snapshot=_snapshot(carrier_up=None))
        for client in _client(tmp_path, service):
            body = client.get("/api/wired").json()

        assert "no_carrier" not in body["warnings"]
        assert body["carrier_up"] is None

    def test_an_advertised_host_that_is_not_the_gateway_warns(self, tmp_path: Path) -> None:
        """A cabled machine cannot reach a LAN address; say so, do not override."""
        service = _StubWiredService()
        for client in _client(tmp_path, service, advertised_host="192.168.5.67"):
            body = client.get("/api/wired").json()

        assert "advertised_host_overrides_gateway" in body["warnings"]

    def test_an_advertised_host_equal_to_the_gateway_does_not_warn(self, tmp_path: Path) -> None:
        service = _StubWiredService()
        for client in _client(tmp_path, service, advertised_host="10.10.10.1"):
            body = client.get("/api/wired").json()

        assert "advertised_host_overrides_gateway" not in body["warnings"]


class TestTheControlGate:
    """Host-network control off means nothing mutating reaches the service."""

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_every_mutation_is_403_while_control_is_off(
        self, tmp_path: Path, method: str, path: str, body: dict[str, object] | None
    ) -> None:
        service = _StubWiredService()
        for client in _client(tmp_path, service, control_enabled=False):
            response = getattr(client, method)(path, **({} if body is None else {"json": body}))

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "wired_control_disabled"
        # The service was never asked — the gate is not advisory.
        assert service.mutations == []


class TestTheConsolePasswordGate:
    """An open console must not be able to put a stranger on this API's segment."""

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_every_mutation_is_409_while_no_password_is_set(
        self, tmp_path: Path, method: str, path: str, body: dict[str, object] | None
    ) -> None:
        service = _StubWiredService()
        for client in _client(tmp_path, service, password_set=False):
            response = getattr(client, method)(path, **({} if body is None else {"json": body}))

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "console_password_required"
        assert service.mutations == []

    def test_control_is_reported_before_the_password(self, tmp_path: Path) -> None:
        """Both gates failing names the first thing to fix, not the second."""
        service = _StubWiredService()
        for client in _client(tmp_path, service, control_enabled=False, password_set=False):
            response = client.post("/api/wired/enable", json={})

        assert response.json()["detail"]["code"] == "wired_control_disabled"


class TestMutationsWhenAllowed:
    """With both gates satisfied, each route reaches its service method."""

    @pytest.mark.parametrize(
        ("method", "path", "body", "expected_call"),
        [
            ("put", "/api/wired", {"enabled": True}, "apply_configuration"),
            ("post", "/api/wired/enable", {}, "enable"),
            ("post", "/api/wired/disable", {}, "disable"),
            ("post", "/api/wired/confirm", None, "confirm"),
            ("delete", "/api/wired", None, "forget"),
            ("delete", "/api/wired/clients/aa:bb:cc:dd:ee:ff", None, "release_lease"),
        ],
    )
    def test_the_route_calls_its_service_method(
        self,
        tmp_path: Path,
        method: str,
        path: str,
        body: dict[str, object] | None,
        expected_call: str,
    ) -> None:
        service = _StubWiredService()
        for client in _client(tmp_path, service):
            response = getattr(client, method)(path, **({} if body is None else {"json": body}))

        assert response.status_code in (200, 204)
        assert service.mutations == [expected_call]


class TestErrorTranslation:
    """Each service error code maps to the status an operator's client expects."""

    @pytest.mark.parametrize(
        ("code", "expected_status"),
        [
            ("wired_unavailable", 503),
            ("wired_not_configured", 409),
            ("uplink_loss_unconfirmed", 409),
            ("no_wired_interface", 409),
            ("interface_not_found", 409),
            ("wired_busy", 409),
            ("wired_not_running", 409),
            ("lease_not_found", 404),
            ("leases_unreadable", 503),
            ("no_pending_confirmation", 409),
            ("wired_command_timeout", 504),
            ("wired_command_failed", 500),
        ],
    )
    def test_known_codes_map_to_their_status(
        self, tmp_path: Path, code: str, expected_status: int
    ) -> None:
        service = _StubWiredService(error=WiredError(code, "nope"))
        for client in _client(tmp_path, service):
            response = client.post("/api/wired/enable", json={})

        assert response.status_code == expected_status
        assert response.json()["detail"]["code"] == code

    def test_an_unmapped_code_falls_back_loudly_to_500(self, tmp_path: Path) -> None:
        """A code absent from the table is a bug, not a quietly-handled case."""
        service = _StubWiredService(error=WiredError("something_new", "nope"))
        for client in _client(tmp_path, service):
            response = client.post("/api/wired/enable", json={})

        assert response.status_code == 500

    def test_command_output_rides_along_in_the_detail(self, tmp_path: Path) -> None:
        """The only thing that says *why* NetworkManager refused."""
        service = _StubWiredService(
            error=WiredError("wired_command_failed", "nope", stderr_tail="Error: no such device")
        )
        for client in _client(tmp_path, service):
            response = client.post("/api/wired/enable", json={})

        assert response.json()["detail"]["stderr_tail"] == "Error: no such device"


class TestListingPorts:
    """`GET /api/wired/interfaces` — what the picker is built from."""

    def test_our_own_share_is_not_reported_as_using_the_port(self, tmp_path: Path) -> None:
        """`in_use_by` non-null reads as "sharing here will cut a link" in the UI."""
        service = _StubWiredService(
            interfaces=(
                WiredInterface(
                    name="eth0",
                    mac_address="DC:A6:32:A9:DC:B0",
                    state="connected",
                    active_connection_name=WIRED_CONNECTION_NAME,
                    ipv4_addresses=("10.10.10.1/24",),
                    carries_default_route=False,
                    carrier_up=True,
                ),
            )
        )
        for client in _client(tmp_path, service):
            body = client.get("/api/wired/interfaces").json()

        assert body["interfaces"][0]["in_use_by"] is None

    def test_another_profile_is_reported_as_using_the_port(self, tmp_path: Path) -> None:
        service = _StubWiredService(
            interfaces=(
                WiredInterface(
                    name="eth0",
                    mac_address="DC:A6:32:A9:DC:B0",
                    state="connected",
                    active_connection_name="Wired connection 1",
                    ipv4_addresses=("192.168.5.67/24",),
                    carries_default_route=True,
                    carrier_up=True,
                ),
            )
        )
        for client in _client(tmp_path, service):
            body = client.get("/api/wired/interfaces").json()

        assert body["interfaces"][0]["in_use_by"] == "Wired connection 1"
        assert body["interfaces"][0]["carries_default_route"] is True

    def test_a_host_with_no_ports_lists_none_rather_than_failing(self, tmp_path: Path) -> None:
        service = _StubWiredService(interfaces=())
        for client in _client(tmp_path, service):
            response = client.get("/api/wired/interfaces")

        assert response.status_code == 200
        assert response.json()["interfaces"] == []


class TestListingLeases:
    """`null` and `[]` are different answers and must stay so."""

    def test_unreadable_leases_are_null_not_empty(self, tmp_path: Path) -> None:
        service = _StubWiredService(clients=None)
        for client in _client(tmp_path, service):
            body = client.get("/api/wired/clients").json()

        assert body["clients"] is None

    def test_no_leases_is_an_empty_list(self, tmp_path: Path) -> None:
        service = _StubWiredService(clients=())
        for client in _client(tmp_path, service):
            body = client.get("/api/wired/clients").json()

        assert body["clients"] == []

    def test_a_lapsed_lease_is_marked_expired_rather_than_hidden(self, tmp_path: Path) -> None:
        """A lease is not an association; dropping the lapsed ones would imply it is."""
        service = _StubWiredService(
            clients=(
                HotspotClient(
                    mac_address="aa:bb:cc:dd:ee:ff",
                    ip_address="10.10.10.42",
                    hostname="laptop",
                    lease_expires_at_ms=1,
                ),
            )
        )
        for client in _client(tmp_path, service):
            body = client.get("/api/wired/clients").json()

        assert len(body["clients"]) == 1
        assert body["clients"][0]["expired"] is True


class TestRequestValidation:
    """The request edge, where an nmcli argv element is first constrained."""

    @pytest.mark.parametrize(
        "gateway_cidr",
        [
            "not-an-address",
            "8.8.8.8/24",  # public range: would blackhole real destinations
            "10.10.10.0/24",  # the network address itself
            "10.10.10.255/24",  # the broadcast address
            "10.10.10.1/31",  # no usable host range for a client
            "10.10.10.1/8",  # wider than /16
        ],
    )
    def test_an_unusable_gateway_is_refused(self, tmp_path: Path, gateway_cidr: str) -> None:
        service = _StubWiredService()
        for client in _client(tmp_path, service):
            response = client.put(
                "/api/wired", json={"enabled": False, "gateway_cidr": gateway_cidr}
            )

        assert response.status_code == 422
        assert service.mutations == []

    def test_an_unknown_field_is_refused_rather_than_ignored(self, tmp_path: Path) -> None:
        """`extra="forbid"`: a typo must not silently mean "leave it at default"."""
        service = _StubWiredService()
        for client in _client(tmp_path, service):
            response = client.put("/api/wired", json={"enabled": False, "ssid": "nope"})

        assert response.status_code == 422

    def test_an_over_long_interface_name_is_refused(self, tmp_path: Path) -> None:
        """Linux caps an interface name at IFNAMSIZ-1 = 15 characters."""
        service = _StubWiredService()
        for client in _client(tmp_path, service):
            response = client.put("/api/wired", json={"enabled": False, "interface": "e" * 16})

        assert response.status_code == 422

    def test_an_empty_body_defaults_to_stopped_and_unconfirmed(self, tmp_path: Path) -> None:
        """The two safety-relevant fields both default to the cautious answer."""
        service = _StubWiredService()
        for client in _client(tmp_path, service):
            response = client.put("/api/wired", json={})

        assert response.status_code == 200
        assert service.mutations == ["apply_configuration"]
