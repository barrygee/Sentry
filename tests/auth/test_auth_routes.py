"""Tests for `/api/auth` and what the session actually protects (ADR-0010).

These assert the *shape of access*, which is the part that would be quietly
wrong: which routes lock, which stay open, and what the session cookie carries.

Run with:  uv run pytest tests/auth
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.main import create_app
from app.backend.services.console_auth import SESSION_COOKIE_NAME

PASSWORD = "a good long password"


MANAGEMENT_ROUTES = [
    pytest.param("/api/status", id="status"),
    pytest.param("/api/devices", id="devices"),
    pytest.param("/api/hotspot", id="hotspot"),
    pytest.param("/api/config", id="config"),
]
"""Management routes exercised over HTTP.

`GET /api/events` is absent on purpose: it is an endless SSE stream, so any
request that is *allowed through* never returns and hangs the suite. Its
protection is asserted structurally in `TestRouterProtection` instead, which is
the stronger check anyway — it fails for a route added tomorrow, not just these.
"""

ALWAYS_OPEN_ROUTES = [
    pytest.param("/api/health", id="health-for-the-docker-healthcheck"),
    pytest.param("/api/v1/sdrs", id="sdr-export-for-sentinel"),
]
"""Routes that must stay reachable with no credential, for reasons ADR-0010 records."""


@pytest.fixture
def app_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], FastAPI]]:
    """Build an app on a throwaway database, with settings cache cleared either side."""
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}")
    get_settings.cache_clear()
    yield create_app
    get_settings.cache_clear()


@pytest.fixture
def client(app_factory: Callable[[], FastAPI]) -> Iterator[TestClient]:
    """A signed-out client against a fresh, open console."""
    with TestClient(app_factory(), raise_server_exceptions=False) as test_client:
        yield test_client


class TestOpenConsole:
    """A fresh install is usable immediately — the documented default."""

    @pytest.mark.parametrize("route", MANAGEMENT_ROUTES)
    def test_management_routes_are_reachable(self, client: TestClient, route: str) -> None:
        assert client.get(route).status_code != 401

    def test_auth_state_reports_open_and_authenticated(self, client: TestClient) -> None:
        # `authenticated: true` with no password is not a lie — there is nothing
        # to authenticate against, and a client rendering a login screen here
        # would be locking a door with no key cut for it.
        body = client.get("/api/auth/state").json()

        assert body["password_set"] is False
        assert body["authenticated"] is True

    def test_logging_in_is_refused_when_no_password_exists(self, client: TestClient) -> None:
        assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 401


class TestSettingTheFirstPassword:
    def test_locks_the_console_for_everyone_else(
        self, client: TestClient, app_factory: Callable[[], FastAPI]
    ) -> None:
        client.post("/api/auth/password", json={"new_password": PASSWORD})

        with TestClient(app_factory(), raise_server_exceptions=False) as other_browser:
            assert other_browser.get("/api/status").status_code == 401

    def test_keeps_the_caller_signed_in(self, client: TestClient) -> None:
        # Otherwise setting a password would immediately throw the operator out
        # of the console they were using, which reads as a failure.
        client.post("/api/auth/password", json={"new_password": PASSWORD})

        assert client.get("/api/status").status_code != 401

    def test_rejects_a_short_password(self, client: TestClient) -> None:
        response = client.post("/api/auth/password", json={"new_password": "short"})

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "password_too_short"

    def test_never_echoes_the_password_back(self, client: TestClient) -> None:
        # A value that appears nowhere in any error text. The first draft used
        # "short", which collides with the `password_too_short` error code — the
        # test failed on its own vocabulary rather than on a leak.
        rejected = "hunter2"

        response = client.post("/api/auth/password", json={"new_password": rejected})

        assert rejected not in response.text


class TestSignedInAccess:
    @pytest.fixture
    def locked(self, client: TestClient) -> TestClient:
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        client.post("/api/auth/logout")
        return client

    @pytest.mark.parametrize("route", MANAGEMENT_ROUTES)
    def test_management_routes_are_locked(self, locked: TestClient, route: str) -> None:
        assert locked.get(route).status_code == 401

    @pytest.mark.parametrize("route", ALWAYS_OPEN_ROUTES)
    def test_open_routes_stay_open(self, locked: TestClient, route: str) -> None:
        assert locked.get(route).status_code == 200

    def test_the_wrong_password_is_refused(self, locked: TestClient) -> None:
        assert locked.post("/api/auth/login", json={"password": "wrong"}).status_code == 401

    def test_the_right_password_signs_in(self, locked: TestClient) -> None:
        assert locked.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
        assert locked.get("/api/status").status_code == 200

    def test_a_failed_login_says_nothing_useful(self, locked: TestClient) -> None:
        # Identical answer whatever went wrong, so a guess learns nothing about
        # which half was right.
        wrong = locked.post("/api/auth/login", json={"password": "wrong"})

        assert wrong.json()["detail"]["code"] == "invalid_password"
        assert PASSWORD not in wrong.text


class TestTheSessionCookie:
    def test_is_httponly_and_samesite_strict(self, client: TestClient) -> None:
        response = client.post("/api/auth/password", json={"new_password": PASSWORD})

        header = response.headers["set-cookie"]
        # HttpOnly keeps an XSS bug from reading the session out; SameSite=Strict
        # is what removes the CSRF exposure a cookie would otherwise introduce.
        assert "HttpOnly" in header
        assert "samesite=strict" in header.lower()

    def test_is_not_marked_secure(self, client: TestClient) -> None:
        # Deliberate: this console is plain HTTP on a LAN. `Secure` would stop
        # the cookie ever being sent, which is not hardening but a total failure
        # to sign in.
        response = client.post("/api/auth/password", json={"new_password": PASSWORD})

        assert "secure" not in response.headers["set-cookie"].lower()

    def test_logout_clears_it(self, client: TestClient) -> None:
        client.post("/api/auth/password", json={"new_password": PASSWORD})

        client.post("/api/auth/logout")

        assert client.cookies.get(SESSION_COOKIE_NAME) in (None, "")


class TestChangingThePassword:
    @pytest.fixture
    def signed_in(self, client: TestClient) -> TestClient:
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        return client

    def test_requires_the_current_password(self, signed_in: TestClient) -> None:
        response = signed_in.post(
            "/api/auth/password",
            json={"new_password": "a different password", "current_password": "wrong"},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "current_password_incorrect"

    def test_signs_other_browsers_out(
        self, signed_in: TestClient, app_factory: Callable[[], FastAPI]
    ) -> None:
        with TestClient(app_factory(), raise_server_exceptions=False) as other_browser:
            other_browser.post("/api/auth/login", json={"password": PASSWORD})
            assert other_browser.get("/api/status").status_code == 200

            signed_in.post(
                "/api/auth/password",
                json={"new_password": "a different password", "current_password": PASSWORD},
            )

            assert other_browser.get("/api/status").status_code == 401

    def test_keeps_the_caller_signed_in(self, signed_in: TestClient) -> None:
        signed_in.post(
            "/api/auth/password",
            json={"new_password": "a different password", "current_password": PASSWORD},
        )

        assert signed_in.get("/api/status").status_code == 200


class TestRouterProtection:
    """Which routers carry the session dependency, asserted on the routers themselves.

    Structural rather than behavioural, and deliberately so: it covers
    `GET /api/events` — untestable over HTTP here, because an allowed request
    streams forever — and it fails when someone adds a router and forgets to
    protect it, which no request-level test can do.
    """

    def test_every_management_router_requires_a_session(self) -> None:
        from app.backend.routers import config, devices, events, hotspot
        from app.backend.routers import status as status_router
        from app.backend.security import require_console_session

        for module in (status_router, devices, events, hotspot, config):
            dependencies = [marker.dependency for marker in module.router.dependencies]
            assert require_console_session in dependencies, (
                f"{module.__name__} does not require a console session"
            )

    def test_the_open_routers_require_nothing(self) -> None:
        # Both are load-bearing: the Docker healthcheck must reach `/api/health`
        # whatever the password, and Sentinel holds no credential at all.
        from app.backend.routers import health, sdrs

        for module in (health, sdrs):
            assert module.router.dependencies == [], (
                f"{module.__name__} must stay reachable without a session"
            )
