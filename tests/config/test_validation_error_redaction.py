"""Tests that a rejected value never comes back in the 422 body.

FastAPI's default validation handler includes an `input` key echoing the value
that failed. For an ordinary field that is a convenience; for a WiFi passphrase
it hands the rejected credential straight back — into the response, the access
log, and any proxy in between.

`SecretStr` does not prevent it: Pydantic records the raw input on the error
before secret-wrapping applies. The redaction therefore lives at the boundary,
in `main._redacted_validation_handler`, and these tests pin it for both routes
that accept a passphrase.

Run with:  uv run pytest tests/config
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.main import create_app

REJECTED_SECRET = "short12"
"""Seven characters — below the WPA minimum, so it always fails validation."""


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An app on a throwaway SQLite file, with hotspot control on.

    `get_settings` is `lru_cache`d, so the cache is cleared either side of the
    override — otherwise the first test to build settings would pin them for
    every test that followed.
    """
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SENTRY_HOTSPOT_CONTROL_ENABLED", "true")
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    get_settings.cache_clear()

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_hotspot_put_does_not_echo_a_rejected_passphrase(client: TestClient) -> None:
    """`PUT /api/hotspot` — the pre-existing leak this handler closes."""
    response = client.put(
        "/api/hotspot",
        json={"ssid": "Field", "passphrase": REJECTED_SECRET, "security": "wpa2"},
    )

    assert response.status_code == 422
    assert REJECTED_SECRET not in response.text


def test_config_import_does_not_echo_a_rejected_passphrase(client: TestClient) -> None:
    """`POST /api/config` — the same leak, reachable through the new import field."""
    response = client.post(
        "/api/config",
        json={
            "config": {"version": 1, "hotspot": {"ssid": "Field", "passphrase": REJECTED_SECRET}},
            "apply_hotspot": True,
        },
    )

    assert response.status_code == 422
    assert REJECTED_SECRET not in response.text


def test_a_redacted_422_still_says_which_field_and_why(client: TestClient) -> None:
    """Redaction must not cost the client its diagnosis.

    `loc` and `msg` are what a caller acts on; `input` only tells it what it
    just sent. Dropping the third leaves the error just as usable.
    """
    response = client.put(
        "/api/hotspot",
        json={"ssid": "Field", "passphrase": REJECTED_SECRET, "security": "wpa2"},
    )

    errors = response.json()["detail"]
    assert errors[0]["loc"] == ["body", "passphrase"]
    assert "8 to 63 characters" in errors[0]["msg"]
    assert "input" not in errors[0]


def test_redaction_applies_to_non_secret_fields_too(client: TestClient) -> None:
    """Applied to every validation error rather than a remembered list of secret fields.

    A per-field allow-list is one somebody must update the day a second secret
    is added, and forgetting is silent.
    """
    response = client.patch("/api/devices/usb:1-1.1", json={"output_port": 17})

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert all("input" not in error for error in errors)
