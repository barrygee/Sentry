"""Tests for `/api/devices/{id}/reservation` and the `PATCH` gate it enforces.

The enforcement matrix is the load-bearing part. A lock that can be walked
around is not a lock, and the specific thing being protected is narrow: the
*signal*. Retuning a dongle somebody else is decoding breaks them silently,
which is why tuning fields are refused; renaming it harms nobody, which is why
metadata is not. Getting that boundary wrong in either direction is a bug —
too tight and the lock feels arbitrary, too loose and it protects nothing.

Run with:  uv run pytest tests/reservations/test_reservation_routes.py
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.backend.config import get_settings
from app.backend.main import create_app

DEVICE_ID = "serial:ADSB-01"
RESERVATION_PATH = f"/api/devices/{DEVICE_ID}/reservation"
HOLDER = "sentinel:aaa"
OTHER_HOLDER = "sentinel:bbb"
HOLDER_HEADER = "X-Sentry-Reservation-Holder"
PASSWORD = "a good long password"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'res.db'}")
    get_settings.cache_clear()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()


def claim(client: TestClient, holder: str = HOLDER, **overrides: Any) -> Any:
    body = {"holder": holder, "label": "Sentinel — AIR (ADS-B)", "ttl_seconds": 120, **overrides}
    return client.post(RESERVATION_PATH, json=body)


class TestReadingAClaim:
    def test_an_unclaimed_device_answers_200_not_404(self, client: TestClient) -> None:
        # "It is free" is a normal answer to a normal question; making the
        # caller catch an error to learn it would be the wrong shape.
        response = client.get(RESERVATION_PATH)

        assert response.status_code == 200
        assert response.json() == {"reserved": False, "reservation": None}

    def test_reports_a_live_claim(self, client: TestClient) -> None:
        claim(client)

        body = client.get(RESERVATION_PATH).json()

        assert body["reserved"] is True
        assert body["reservation"]["holder"] == HOLDER
        assert body["reservation"]["label"] == "Sentinel — AIR (ADS-B)"


class TestClaiming:
    def test_claiming_a_free_device_succeeds(self, client: TestClient) -> None:
        response = claim(client)

        assert response.status_code == 200
        assert response.json()["holder"] == HOLDER

    def test_the_same_holder_may_renew(self, client: TestClient) -> None:
        first = claim(client).json()

        renewed = claim(client).json()

        assert renewed["expires_at"] >= first["expires_at"]
        assert renewed["reserved_at"] == first["reserved_at"]

    def test_another_holder_is_refused_and_told_who_has_it(self, client: TestClient) -> None:
        claim(client)

        response = claim(client, holder=OTHER_HOLDER)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "device_reserved"
        assert detail["holder"] == HOLDER
        assert detail["expires_at"] > 0

    def test_force_takes_the_device(self, client: TestClient) -> None:
        claim(client)

        response = claim(client, holder=OTHER_HOLDER, force=True)

        assert response.status_code == 200
        assert client.get(RESERVATION_PATH).json()["reservation"]["holder"] == OTHER_HOLDER

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"label": "no holder"}, id="missing-holder"),
            pytest.param({"holder": "", "label": ""}, id="empty-holder"),
            pytest.param({"holder": HOLDER, "ttl_seconds": 0}, id="ttl-too-short"),
            pytest.param({"holder": HOLDER, "ttl_seconds": 99999}, id="ttl-too-long"),
            pytest.param({"holder": HOLDER, "unknown": 1}, id="unknown-field"),
        ],
    )
    def test_rejects_a_malformed_claim(self, client: TestClient, body: dict[str, Any]) -> None:
        assert client.post(RESERVATION_PATH, json=body).status_code == 422


class TestReleasing:
    def test_the_holder_can_release(self, client: TestClient) -> None:
        claim(client)

        response = client.delete(RESERVATION_PATH, headers={HOLDER_HEADER: HOLDER})

        assert response.status_code == 204
        assert client.get(RESERVATION_PATH).json()["reserved"] is False

    def test_releasing_a_free_device_is_a_success(self, client: TestClient) -> None:
        assert client.delete(RESERVATION_PATH, headers={HOLDER_HEADER: HOLDER}).status_code == 204

    def test_another_holder_cannot_release(self, client: TestClient) -> None:
        claim(client)

        response = client.delete(RESERVATION_PATH, headers={HOLDER_HEADER: OTHER_HOLDER})

        assert response.status_code == 409
        assert client.get(RESERVATION_PATH).json()["reserved"] is True

    def test_force_releases_somebody_elses_claim(self, client: TestClient) -> None:
        claim(client)

        response = client.delete(
            f"{RESERVATION_PATH}?force=true", headers={HOLDER_HEADER: OTHER_HOLDER}
        )

        assert response.status_code == 204
        assert client.get(RESERVATION_PATH).json()["reserved"] is False


class TestThePatchGate:
    """What a claim actually buys: nobody else changes the signal.

    These assert on the *reservation* outcome, not on the patch succeeding —
    this host has no real dongle, so an allowed patch goes on to fail with
    `unknown_device`. That is the point: reaching 404 proves the request passed
    the gate, and 409 proves it did not.
    """

    def _patch(self, client: TestClient, body: dict[str, Any], holder: str | None = None) -> Any:
        headers = {HOLDER_HEADER: holder} if holder else {}
        return client.patch(f"/api/devices/{DEVICE_ID}", json=body, headers=headers)

    def test_a_stranger_cannot_retune_a_claimed_device(self, client: TestClient) -> None:
        claim(client)

        response = self._patch(client, {"center_hz": 1_090_000_000})

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "device_reserved"

    def test_another_holder_cannot_retune_it(self, client: TestClient) -> None:
        claim(client)

        response = self._patch(client, {"center_hz": 1_090_000_000}, holder=OTHER_HOLDER)

        assert response.status_code == 409

    def test_the_holder_may_retune_it(self, client: TestClient) -> None:
        claim(client)

        response = self._patch(client, {"center_hz": 1_090_000_000}, holder=HOLDER)

        assert response.status_code != 409

    @pytest.mark.parametrize(
        "field,value",
        [
            pytest.param("center_hz", 1_090_000_000, id="centre-frequency"),
            pytest.param("sample_rate", 2_400_000, id="sample-rate"),
            pytest.param("gain_auto", False, id="gain-mode"),
            pytest.param("ppm_correction", 5, id="ppm"),
            pytest.param("enabled", False, id="enabled"),
        ],
    )
    def test_every_signal_changing_field_is_locked(
        self, client: TestClient, field: str, value: Any
    ) -> None:
        claim(client)

        assert self._patch(client, {field: value}).status_code == 409

    @pytest.mark.parametrize(
        "field,value",
        [
            pytest.param("notes", "a note", id="notes"),
            pytest.param("antenna", "Discone", id="antenna"),
            pytest.param("description", "roof", id="description"),
            pytest.param("visibility", "public", id="visibility"),
        ],
    )
    def test_metadata_is_never_locked(self, client: TestClient, field: str, value: Any) -> None:
        # Renaming a device harms nobody; refusing it would make the lock feel
        # arbitrary and push operators towards forcing it off out of habit.
        claim(client)

        assert self._patch(client, {field: value}).status_code != 409

    def test_an_unclaimed_device_may_be_retuned_freely(self, client: TestClient) -> None:
        assert self._patch(client, {"center_hz": 1_090_000_000}).status_code != 409

    def test_a_released_claim_stops_blocking(self, client: TestClient) -> None:
        """The operator's escape hatch: force the claim off, then edit freely.

        Expiry gets the operator there too, but only the service tests can drive
        a clock — over HTTP the wait would be real seconds, so lapse is asserted
        in `test_reservation_service.py` and this covers the deliberate route.
        """
        claim(client)

        client.delete(f"{RESERVATION_PATH}?force=true", headers={HOLDER_HEADER: OTHER_HOLDER})

        assert self._patch(client, {"center_hz": 1_090_000_000}).status_code != 409


class TestTheSessionGate:
    @pytest.mark.parametrize("method", ["get", "post", "delete"])
    def test_reservation_routes_require_a_session(self, client: TestClient, method: str) -> None:
        # A dongle's claim is management state: an unauthenticated caller could
        # otherwise take a device from whoever is using it.
        client.post("/api/auth/password", json={"new_password": PASSWORD})
        client.post("/api/auth/logout")

        request = getattr(client, method)
        response = request(
            RESERVATION_PATH, **({"json": {"holder": HOLDER}} if method == "post" else {})
        )

        assert response.status_code == 401
