"""Tests for `PUT /api/hotspot/control`, the route that grants the capability (ADR-0013).

Every other hotspot route is guarded by the switch this one sets, so this is
where the trust boundary now sits. ADR-0007 made shell access to the Pi the
thing standing between a stranger and the host's networking; moving the switch
into the console replaces that with the console password, which is why the
refusal below is a hard `409` and not a hidden button.

Asserted over HTTP rather than against the service, because the gate is a check
in a route — a UI that hid the control would be presentation, and presentation
is not what protects the host.

Run with:  uv run pytest tests/hotspot
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.main import create_app

PASSWORD = "a good long password"


@pytest.fixture
def app_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], FastAPI]]:
    """Build an app on a throwaway database, with settings cache cleared either side."""
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'hotspot.db'}")
    monkeypatch.setenv("SENTRY_HOTSPOT_CONTROL_ENABLED", "false")
    get_settings.cache_clear()
    yield create_app
    get_settings.cache_clear()


@pytest.fixture
def client(app_factory: Callable[[], FastAPI]) -> Iterator[TestClient]:
    """A client against a fresh, open console with hotspot control switched off."""
    with TestClient(app_factory(), raise_server_exceptions=False) as test_client:
        yield test_client


class TestConsolePasswordGate:
    def test_an_open_console_cannot_switch_hotspot_control_on(self, client: TestClient) -> None:
        """The whole reason this is safe to expose: no password, no host networking."""
        response = client.put("/api/hotspot/control", json={"enabled": True})

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "console_password_required"

    def test_a_refused_call_leaves_control_off(self, client: TestClient) -> None:
        """A 409 that had already written the value would be worse than no gate at all."""
        client.put("/api/hotspot/control", json={"enabled": True})

        assert client.get("/api/hotspot").json()["control_enabled"] is False

    def test_switching_off_is_refused_without_a_password_too(self, client: TestClient) -> None:
        """The gate is on the route, not on the direction of travel."""
        response = client.put("/api/hotspot/control", json={"enabled": False})

        assert response.status_code == 409


class TestWithAPasswordSet:
    @pytest.fixture
    def signed_in(self, client: TestClient) -> TestClient:
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        return client

    def test_control_can_be_switched_on(self, signed_in: TestClient) -> None:
        response = signed_in.put("/api/hotspot/control", json={"enabled": True})

        assert response.status_code == 200
        assert response.json()["control_enabled"] is True

    def test_the_change_is_visible_to_the_hotspot_route(self, signed_in: TestClient) -> None:
        """Without a restart — the entire point of moving it out of `.env`."""
        signed_in.put("/api/hotspot/control", json={"enabled": True})

        assert signed_in.get("/api/hotspot").json()["control_enabled"] is True

    def test_control_can_be_switched_off_again(self, signed_in: TestClient) -> None:
        signed_in.put("/api/hotspot/control", json={"enabled": True})

        signed_in.put("/api/hotspot/control", json={"enabled": False})

        assert signed_in.get("/api/hotspot").json()["control_enabled"] is False

    def test_mutating_routes_are_refused_while_control_is_off(self, signed_in: TestClient) -> None:
        """The switch actually gates something — otherwise it is decoration."""
        response = signed_in.post("/api/hotspot/disable", json={"confirm_uplink_loss": False})

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "hotspot_control_disabled"

    def test_the_refusal_no_longer_tells_operators_to_edit_env(self, signed_in: TestClient) -> None:
        """It used to name an environment variable; that instruction is now wrong."""
        response = signed_in.post("/api/hotspot/disable", json={"confirm_uplink_loss": False})

        assert "SENTRY_HOTSPOT_CONTROL_ENABLED" not in response.json()["detail"]["message"]

    def test_an_unauthenticated_browser_cannot_switch_control_on(
        self, signed_in: TestClient, app_factory: Callable[[], FastAPI]
    ) -> None:
        """A password protects the switch only if the session is actually required."""
        with TestClient(app_factory(), raise_server_exceptions=False) as other_browser:
            response = other_browser.put("/api/hotspot/control", json={"enabled": True})

        assert response.status_code == 401


class TestEnvironmentOverride:
    def test_the_environment_variable_still_forces_control_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator relying on `.env` must not be quietly switched off by a stored value."""
        monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'forced.db'}")
        monkeypatch.setenv("SENTRY_HOTSPOT_CONTROL_ENABLED", "true")
        get_settings.cache_clear()

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            client.post("/api/auth/password", json={"new_password": PASSWORD})
            client.put("/api/hotspot/control", json={"enabled": False})

            body = client.get("/api/hotspot").json()

        get_settings.cache_clear()
        assert body["control_enabled"] is True
