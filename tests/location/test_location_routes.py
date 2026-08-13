"""Tests for `/api/location` and the two Sentinel-facing surfaces that publish it.

The load-bearing assertion here is the last class: the position must reach
Sentinel **in the call it already makes**, otherwise the feature works in this
console and does nothing for the map it exists to serve.

Run with:  uv run pytest tests/location
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.main import create_app

LATITUDE = 54.95149
LONGITUDE = -1.53586
PASSWORD = "a good long password"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'location.db'}")
    get_settings.cache_clear()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()


class TestReadingTheLocation:
    def test_a_fresh_sentry_reports_no_position(self, client: TestClient) -> None:
        body = client.get("/api/location").json()

        assert body["latitude"] is None
        assert body["longitude"] is None
        assert body["updated_at"] == 0


class TestSettingTheLocation:
    def test_stores_and_returns_the_pair(self, client: TestClient) -> None:
        response = client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        assert response.status_code == 200
        assert response.json()["latitude"] == LATITUDE
        assert response.json()["longitude"] == LONGITUDE

    def test_the_stored_pair_survives_a_reread(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        assert client.get("/api/location").json()["longitude"] == LONGITUDE

    def test_two_nulls_clear_the_position(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        response = client.put("/api/location", json={"latitude": None, "longitude": None})

        assert response.status_code == 200
        assert client.get("/api/location").json()["latitude"] is None

    def test_a_later_write_replaces_an_earlier_one(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        client.put("/api/location", json={"latitude": 1.5, "longitude": 2.5})

        assert client.get("/api/location").json()["latitude"] == 1.5


class TestRejectedBodies:
    """Every one of these is a plausible typo that would otherwise mis-plot the Sentry."""

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"latitude": LATITUDE}, id="latitude-alone"),
            pytest.param({"longitude": LONGITUDE}, id="longitude-alone"),
            pytest.param({"latitude": LATITUDE, "longitude": None}, id="explicit-null-longitude"),
        ],
    )
    def test_refuses_half_a_position(self, client: TestClient, body: dict[str, object]) -> None:
        assert client.put("/api/location", json=body).status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"latitude": 91, "longitude": 0}, id="latitude-too-high"),
            pytest.param({"latitude": -91, "longitude": 0}, id="latitude-too-low"),
            pytest.param({"latitude": 0, "longitude": 181}, id="longitude-too-high"),
            pytest.param({"latitude": 0, "longitude": -181}, id="longitude-too-low"),
        ],
    )
    def test_refuses_a_coordinate_off_the_globe(
        self, client: TestClient, body: dict[str, object]
    ) -> None:
        assert client.put("/api/location", json=body).status_code == 422

    def test_refuses_an_unknown_field(self, client: TestClient) -> None:
        response = client.put(
            "/api/location",
            json={"latitude": LATITUDE, "longitude": LONGITUDE, "altitude": 100},
        )

        assert response.status_code == 422

    def test_a_rejected_write_leaves_the_stored_position_alone(self, client: TestClient) -> None:
        # A partial write would be the worst outcome: the map would move to a
        # position nobody chose.
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        client.put("/api/location", json={"latitude": 91, "longitude": 0})

        assert client.get("/api/location").json()["latitude"] == LATITUDE


class TestTheSessionGate:
    def test_a_signed_out_browser_cannot_read_the_position(self, client: TestClient) -> None:
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        client.post("/api/auth/logout")

        assert client.get("/api/location").status_code == 401

    def test_a_signed_out_browser_cannot_move_the_sentry(self, client: TestClient) -> None:
        # The negative case that matters: an unauthenticated writer could
        # relocate this Sentry on every Sentinel watching it.
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        client.post("/api/auth/logout")

        response = client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        assert response.status_code == 401
        client.post("/api/auth/login", json={"password": PASSWORD})
        assert client.get("/api/location").json()["latitude"] is None


class TestWhatSentinelReceives:
    """The whole point of the feature: coordinates arrive with the device list."""

    def test_status_carries_the_position(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        location = client.get("/api/status").json()["location"]

        assert location["latitude"] == LATITUDE
        assert location["longitude"] == LONGITUDE

    def test_status_carries_an_unset_position_rather_than_omitting_it(
        self, client: TestClient
    ) -> None:
        # The key must always be present, so a consumer can read it without
        # branching on its existence.
        location = client.get("/api/status").json()["location"]

        assert location["latitude"] is None

    def test_the_versioned_export_carries_it_on_source(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        source = client.get("/api/v1/sdrs").json()["source"]

        assert source["location"]["latitude"] == LATITUDE
        assert source["location"]["longitude"] == LONGITUDE

    def test_the_permanent_alias_carries_it_too(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        source = client.get("/api/sdrs").json()["source"]

        assert source["location"]["latitude"] == LATITUDE

    def test_the_export_reports_a_position_even_with_no_public_devices(
        self, client: TestClient
    ) -> None:
        # Location is a fact about the instance, not about a dongle, so a Sentry
        # publishing nothing is still plottable.
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        body = client.get("/api/v1/sdrs").json()

        assert body["sdrs"] == []
        assert body["source"]["location"]["latitude"] == LATITUDE

    def test_the_export_stays_readable_without_a_session(self, client: TestClient) -> None:
        # Sentinel holds no credential (ADR-0010), so this is the surface that
        # has to keep working once a password exists.
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        client.post("/api/auth/logout")

        response = client.get("/api/v1/sdrs")

        assert response.status_code == 200
        assert response.json()["source"]["location"]["latitude"] == LATITUDE

    def test_clearing_the_position_removes_it_from_the_export(self, client: TestClient) -> None:
        client.put("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        client.put("/api/location", json={"latitude": None, "longitude": None})

        assert client.get("/api/v1/sdrs").json()["source"]["location"]["latitude"] is None
