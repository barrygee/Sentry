"""Tests for the fixed position travelling in the config file.

Three properties carry real consequences and would each fail quietly:

* **An unset position exports as `""`, not `null` or a missing key.** The file
  is the artefact an operator opens in a text editor to fill in, and a visible
  blank is the whole reason the section is written even when empty.
* **An empty section never clears a position the destination already has.**
  Every export now carries the section, so importing a file from an unplaced
  Sentry onto a placed one would otherwise silently wipe it.
* **`apply_location` can be switched off.** Cloning one Pi's file onto another
  is the case where applying the position is wrong, and the flag is the only
  thing standing between that and two Sentries at one address.

Run with:  uv run pytest tests/config/test_location_config.py
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.backend.config import get_settings
from app.backend.main import create_app
from app.backend.schemas.config import LocationConfigEntry, SentryConfig

LATITUDE = 54.95149
LONGITUDE = -1.53586


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SENTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cfgloc.db'}")
    get_settings.cache_clear()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()


def store_position(client: TestClient, latitude: float, longitude: float) -> None:
    client.put("/api/location", json={"latitude": latitude, "longitude": longitude})


def import_body(config: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {"config": config, "apply_devices": False, **overrides}


class TestTheEntryShape:
    def test_serialises_an_unset_coordinate_as_an_empty_string(self) -> None:
        dumped = LocationConfigEntry().model_dump(mode="json")

        assert dumped == {"latitude": "", "longitude": ""}

    def test_serialises_a_set_coordinate_as_a_number(self) -> None:
        # Numbers, not strings: anything reading the file can do maths on them
        # without parsing first.
        dumped = LocationConfigEntry(latitude=LATITUDE, longitude=LONGITUDE).model_dump(mode="json")

        assert dumped == {"latitude": LATITUDE, "longitude": LONGITUDE}

    def test_reads_an_empty_string_back_as_no_position(self) -> None:
        entry = LocationConfigEntry.model_validate({"latitude": "", "longitude": ""})

        assert entry.latitude is None
        assert entry.is_set is False

    def test_reads_a_whitespace_only_field_as_no_position(self) -> None:
        # A hand-edited file is the expected input, and `" "` is `""` typed
        # slightly worse.
        entry = LocationConfigEntry.model_validate({"latitude": "  ", "longitude": ""})

        assert entry.is_set is False

    def test_round_trips_a_set_position(self) -> None:
        entry = LocationConfigEntry(latitude=LATITUDE, longitude=LONGITUDE)

        reparsed = LocationConfigEntry.model_validate(entry.model_dump(mode="json"))

        assert (reparsed.latitude, reparsed.longitude) == (LATITUDE, LONGITUDE)

    def test_round_trips_an_unset_position(self) -> None:
        # The empty strings it writes must be readable by the importer that
        # receives them — the failure would only appear on re-import.
        entry = LocationConfigEntry()

        reparsed = LocationConfigEntry.model_validate(entry.model_dump(mode="json"))

        assert reparsed.is_set is False

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"latitude": LATITUDE, "longitude": ""}, id="half-a-position"),
            pytest.param({"latitude": "", "longitude": LONGITUDE}, id="other-half"),
            pytest.param({"latitude": 91, "longitude": 0}, id="latitude-off-the-globe"),
            pytest.param({"latitude": 0, "longitude": 181}, id="longitude-off-the-globe"),
            pytest.param({"latitude": 1, "longitude": 2, "altitude": 3}, id="unknown-field"),
            pytest.param({"latitude": "north", "longitude": 2}, id="not-a-number"),
        ],
    )
    def test_rejects_a_hand_edited_mistake(self, payload: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            LocationConfigEntry.model_validate(payload)


class TestExporting:
    def test_writes_empty_strings_when_no_position_is_set(self, client: TestClient) -> None:
        exported = client.get("/api/config").json()

        assert exported["location"] == {"latitude": "", "longitude": ""}

    def test_writes_the_stored_position(self, client: TestClient) -> None:
        store_position(client, LATITUDE, LONGITUDE)

        exported = client.get("/api/config").json()

        assert exported["location"] == {"latitude": LATITUDE, "longitude": LONGITUDE}

    def test_reflects_a_position_set_through_the_post_alias(self, client: TestClient) -> None:
        client.post("/api/location", json={"latitude": LATITUDE, "longitude": LONGITUDE})

        assert client.get("/api/config").json()["location"]["latitude"] == LATITUDE

    def test_the_downloadable_file_carries_it_too(self, client: TestClient) -> None:
        store_position(client, LATITUDE, LONGITUDE)

        downloaded = json.loads(client.get("/api/config/download").text)

        assert downloaded["location"] == {"latitude": LATITUDE, "longitude": LONGITUDE}

    def test_the_downloadable_file_carries_empty_strings_when_unset(
        self, client: TestClient
    ) -> None:
        downloaded = json.loads(client.get("/api/config/download").text)

        assert downloaded["location"] == {"latitude": "", "longitude": ""}


class TestImporting:
    def test_applies_the_file_s_position(self, client: TestClient) -> None:
        store_position(client, LATITUDE, LONGITUDE)
        exported = client.get("/api/config").json()
        client.put("/api/location", json={"latitude": None, "longitude": None})

        result = client.post("/api/config", json=import_body(exported)).json()

        assert result["location_applied"] is True
        assert client.get("/api/location").json()["latitude"] == LATITUDE

    def test_an_empty_section_does_not_clear_a_stored_position(self, client: TestClient) -> None:
        # The destructive case this guards: a file exported from an unplaced
        # Sentry, imported onto a placed one.
        empty_file = client.get("/api/config").json()
        store_position(client, LATITUDE, LONGITUDE)

        result = client.post("/api/config", json=import_body(empty_file)).json()

        assert result["location_applied"] is False
        assert result["location_detail"] != ""
        assert client.get("/api/location").json()["latitude"] == LATITUDE

    def test_apply_location_false_leaves_the_position_alone(self, client: TestClient) -> None:
        store_position(client, LATITUDE, LONGITUDE)
        exported = client.get("/api/config").json()
        store_position(client, 1.5, 2.5)

        result = client.post("/api/config", json=import_body(exported, apply_location=False)).json()

        assert result["location_applied"] is False
        assert client.get("/api/location").json()["latitude"] == 1.5

    def test_applies_by_default_without_the_flag_being_named(self, client: TestClient) -> None:
        # Restoring a backup is the common case, so it must not need a flag.
        store_position(client, LATITUDE, LONGITUDE)
        exported = client.get("/api/config").json()
        client.put("/api/location", json={"latitude": None, "longitude": None})

        client.post("/api/config", json={"config": exported, "apply_devices": False})

        assert client.get("/api/location").json()["latitude"] == LATITUDE

    def test_a_hand_written_position_is_applied(self, client: TestClient) -> None:
        result = client.post(
            "/api/config",
            json=import_body({"version": 1, "location": {"latitude": 51.5, "longitude": -0.12}}),
        ).json()

        assert result["location_applied"] is True
        assert client.get("/api/location").json()["longitude"] == -0.12

    def test_a_hand_written_half_pair_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/config",
            json=import_body({"version": 1, "location": {"latitude": 51.5, "longitude": ""}}),
        )

        assert response.status_code == 422

    def test_a_file_predating_the_section_is_reported_not_applied(self, client: TestClient) -> None:
        # `location` absent entirely, as an older Sentry wrote it.
        store_position(client, LATITUDE, LONGITUDE)

        result = client.post("/api/config", json=import_body({"version": 1})).json()

        assert result["location_applied"] is False
        assert result["location_detail"] != ""
        assert client.get("/api/location").json()["latitude"] == LATITUDE


class TestTheExampleFile:
    def test_the_shipped_example_carries_a_location(self) -> None:
        """`config.example.json` documents the shape, so it must show this section."""
        with open("config.example.json", encoding="utf-8") as handle:
            example = json.load(handle)

        assert "location" in example
        parsed = SentryConfig.model_validate(example)
        assert parsed.location is not None
        assert parsed.location.is_set is True
