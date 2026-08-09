"""Tests for provisioning a controller password from a config file (ADR-0010).

The same import-only mechanism as the hotspot passphrase: a hand-written file
may carry one inwards, and no file Sentry produces can carry one outwards.

The rule with teeth is that a file may only set a **first** password. An import
is the action people most routinely perform with a file somebody else gave them,
and without that rule it would silently replace the credential and sign
everybody out — including whoever ran it.

Run with:  uv run pytest tests/config
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.backend.config import get_settings
from app.backend.main import create_app
from app.backend.schemas.config import SentryConfig
from app.backend.services.console_auth import SESSION_COOKIE_NAME

PASSWORD = "provisioned-password"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'prov.db'}")
    get_settings.cache_clear()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()


def provisioning_file(password: str | None = PASSWORD) -> dict[str, object]:
    config: dict[str, object] = {"version": 1}
    if password is not None:
        config["console_password"] = password
    return {"config": config, "apply_devices": False}


class TestTheSchema:
    def test_parses_a_password_from_a_file(self) -> None:
        parsed = SentryConfig.model_validate({"version": 1, "console_password": PASSWORD})

        assert parsed.console_password is not None
        assert parsed.console_password.get_secret_value() == PASSWORD

    def test_never_serialises_it_back_out(self) -> None:
        # Asserting the *key* is absent, not just the value: `SecretStr` alone
        # would render `"console_password": "**********"`, which passes
        # validation on the way back in and would set the password to ten
        # literal asterisks.
        parsed = SentryConfig.model_validate({"version": 1, "console_password": PASSWORD})

        exported = json.loads(parsed.model_dump_json())

        assert "console_password" not in exported
        assert PASSWORD not in parsed.model_dump_json()

    def test_rejects_one_below_the_minimum(self) -> None:
        with pytest.raises(ValidationError):
            SentryConfig.model_validate({"version": 1, "console_password": "abc"})

    def test_a_file_without_one_parses_to_none(self) -> None:
        assert SentryConfig.model_validate({"version": 1}).console_password is None


class TestImporting:
    def test_sets_the_first_password(self, client: TestClient) -> None:
        result = client.post("/api/config", json=provisioning_file()).json()

        assert result["console_password_applied"] is True
        assert client.get("/api/auth/state").json()["password_set"] is True

    def test_signs_the_caller_in_rather_than_locking_them_out(self, client: TestClient) -> None:
        # The import's per-entry report is the whole point of the response.
        # Without a fresh session the operator is bounced to a sign-in screen
        # before they can read it — by their own successful import.
        response = client.post("/api/config", json=provisioning_file())

        assert SESSION_COOKIE_NAME in response.headers.get("set-cookie", "")
        assert client.get("/api/status").status_code == 200

    def test_refuses_to_replace_an_existing_password(self, client: TestClient) -> None:
        client.post("/api/config", json=provisioning_file())

        result = client.post("/api/config", json=provisioning_file("a-different-password")).json()

        assert result["console_password_applied"] is False
        assert "already has a password" in result["console_password_detail"]

    def test_the_original_password_still_works_after_a_refused_replace(
        self, client: TestClient
    ) -> None:
        client.post("/api/config", json=provisioning_file())
        client.post("/api/config", json=provisioning_file("a-different-password"))

        client.post("/api/auth/logout")

        assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204

    def test_a_file_without_a_password_changes_nothing(self, client: TestClient) -> None:
        result = client.post("/api/config", json=provisioning_file(None)).json()

        assert result["console_password_applied"] is False
        assert client.get("/api/auth/state").json()["password_set"] is False

    def test_never_echoes_the_password(self, client: TestClient) -> None:
        response = client.post("/api/config", json=provisioning_file())

        assert PASSWORD not in response.text


class TestExporting:
    @pytest.mark.parametrize("route", ["/api/config", "/api/config/download"])
    def test_no_export_carries_the_password(self, client: TestClient, route: str) -> None:
        client.post("/api/config", json=provisioning_file())

        assert PASSWORD not in client.get(route).text
