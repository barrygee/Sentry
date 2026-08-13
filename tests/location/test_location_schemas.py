"""Tests for the location schemas' two rules: coordinate bounds, and both-or-neither.

Both would fail silently in the way that matters most here. An out-of-range
longitude is still a number, and a half-set pair is still a valid-looking
object — neither raises anywhere until Sentinel tries to place a marker and
puts this Sentry somewhere it is not.

Run with:  uv run pytest tests/location/test_location_schemas.py
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.backend.schemas.location import SentryLocation, SentryLocationUpdate

LATITUDE = 54.95149
LONGITUDE = -1.53586


class TestTheUnsetPosition:
    def test_defaults_to_no_position(self) -> None:
        location = SentryLocation()

        assert location.latitude is None
        assert location.longitude is None
        assert location.updated_at == 0
        assert location.is_set is False

    def test_a_complete_pair_reports_itself_set(self) -> None:
        location = SentryLocation(latitude=LATITUDE, longitude=LONGITUDE)

        assert location.is_set is True

    def test_zero_zero_is_a_set_position_not_an_unset_one(self) -> None:
        # Null Island is a real coordinate. If `0.0` were treated as "unset",
        # a Sentry deliberately placed there would vanish from Sentinel's map —
        # which is exactly why the unset state is `None` and not `0`.
        location = SentryLocation(latitude=0.0, longitude=0.0)

        assert location.is_set is True


class TestCoordinateBounds:
    @pytest.mark.parametrize("latitude", [-90.0, 0.0, 90.0])
    def test_accepts_latitudes_at_and_inside_the_limits(self, latitude: float) -> None:
        assert SentryLocation(latitude=latitude, longitude=0.0).latitude == latitude

    @pytest.mark.parametrize("longitude", [-180.0, 0.0, 180.0])
    def test_accepts_longitudes_at_and_inside_the_limits(self, longitude: float) -> None:
        assert SentryLocation(latitude=0.0, longitude=longitude).longitude == longitude

    @pytest.mark.parametrize("latitude", [-90.1, 90.1, 900.0])
    def test_rejects_a_latitude_off_the_globe(self, latitude: float) -> None:
        with pytest.raises(ValidationError):
            SentryLocation(latitude=latitude, longitude=0.0)

    @pytest.mark.parametrize("longitude", [-180.1, 180.1, 900.0])
    def test_rejects_a_longitude_off_the_globe(self, longitude: float) -> None:
        with pytest.raises(ValidationError):
            SentryLocation(latitude=0.0, longitude=longitude)


class TestTheBothOrNeitherRule:
    """Half a position cannot be plotted, so it is never a state worth storing."""

    def test_rejects_a_latitude_without_a_longitude(self) -> None:
        with pytest.raises(ValidationError, match="set together"):
            SentryLocation(latitude=LATITUDE)

    def test_rejects_a_longitude_without_a_latitude(self) -> None:
        with pytest.raises(ValidationError, match="set together"):
            SentryLocation(longitude=LONGITUDE)

    def test_the_update_body_rejects_a_latitude_alone(self) -> None:
        with pytest.raises(ValidationError, match="set together"):
            SentryLocationUpdate(latitude=LATITUDE)

    def test_the_update_body_rejects_a_longitude_alone(self) -> None:
        with pytest.raises(ValidationError, match="set together"):
            SentryLocationUpdate(longitude=LONGITUDE)

    def test_the_update_body_accepts_a_complete_pair(self) -> None:
        update = SentryLocationUpdate(latitude=LATITUDE, longitude=LONGITUDE)

        assert (update.latitude, update.longitude) == (LATITUDE, LONGITUDE)

    def test_the_update_body_accepts_two_nulls_as_an_erasure(self) -> None:
        # The only way an operator clears a position, so it must stay valid.
        update = SentryLocationUpdate(latitude=None, longitude=None)

        assert update.latitude is None
        assert update.longitude is None


class TestTheUpdateBodyIsStrict:
    def test_rejects_an_unknown_field(self) -> None:
        # `extra="forbid"`, so an operator's typo is an error rather than a
        # silently-dropped key that leaves the position unchanged.
        with pytest.raises(ValidationError):
            SentryLocationUpdate.model_validate(
                {"latitude": LATITUDE, "longitude": LONGITUDE, "altitude": 100}
            )

    def test_rejects_a_non_numeric_coordinate(self) -> None:
        with pytest.raises(ValidationError):
            SentryLocationUpdate.model_validate({"latitude": "north", "longitude": LONGITUDE})
