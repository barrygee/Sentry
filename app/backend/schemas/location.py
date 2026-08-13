"""`/api/location` — this Sentry's fixed geographic position.

An operator types a latitude/longitude once, and every Sentinel that queries
this Sentry can plot it on a map. The alternative was Sentinel holding a
per-host location of its own, which puts the fact in the wrong place: the Pi
knows where it is, and a second Sentinel would have to be told again.

The position is published on `GET /api/status` and in `GET /api/v1/sdrs`'s
`source` block, so it arrives alongside the device list in the one call
Sentinel already makes rather than needing a second round trip (§7.7).

**These coordinates are readable by anyone who can reach `/api/v1/sdrs`**,
which is unauthenticated by design (ADR-0010). That is the same trade the
export already makes for device names and IQ ports, and it is what lets a
Sentinel with no credential draw the map at all — but it does mean the
position of the Pi is not a secret from the network it sits on.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

MINIMUM_LATITUDE = -90.0
MAXIMUM_LATITUDE = 90.0
MINIMUM_LONGITUDE = -180.0
MAXIMUM_LONGITUDE = 180.0


class SentryLocation(BaseModel):
    """This instance's position — `GET /api/location`, and the value published to Sentinel.

    `latitude`/`longitude` are both `None` until an operator sets a position.
    They are always both-or-neither: a lone latitude cannot be plotted and is
    only ever a half-finished edit, so the pair is validated as a unit rather
    than letting one arrive without the other.
    """

    model_config = ConfigDict(frozen=True)

    latitude: float | None = Field(
        default=None,
        ge=MINIMUM_LATITUDE,
        le=MAXIMUM_LATITUDE,
        description="Decimal degrees. Null when the operator has not set a position",
    )
    longitude: float | None = Field(
        default=None,
        ge=MINIMUM_LONGITUDE,
        le=MAXIMUM_LONGITUDE,
        description="Decimal degrees. Null when the operator has not set a position",
    )
    updated_at: int = Field(default=0, description="Unix ms the position last changed")

    @property
    def is_set(self) -> bool:
        """Whether a plottable position exists. Both coordinates or neither."""
        return self.latitude is not None and self.longitude is not None

    @model_validator(mode="after")
    def _check_pair_is_complete(self) -> SentryLocation:
        """Refuse half a position.

        Nothing downstream can do anything useful with one coordinate, and a
        stored half-pair would be indistinguishable from a set position right
        up until Sentinel tried to place the marker.
        """
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be set together, or both left empty.")
        return self


class SentryLocationUpdate(BaseModel):
    """`PUT /api/location` body — the position to store, or `null`s to clear it.

    Deliberately a PUT with both fields required-but-nullable rather than a
    PATCH of optional keys. An omitted key in a patch is ambiguous here ("leave
    it alone" or "clear it"?), and the only two things an operator ever wants
    are *set this pair* and *unset the position entirely* — both of which this
    body says unambiguously.
    """

    model_config = ConfigDict(extra="forbid")

    latitude: float | None = Field(
        default=None, ge=MINIMUM_LATITUDE, le=MAXIMUM_LATITUDE, description="Decimal degrees"
    )
    longitude: float | None = Field(
        default=None, ge=MINIMUM_LONGITUDE, le=MAXIMUM_LONGITUDE, description="Decimal degrees"
    )

    @model_validator(mode="after")
    def _check_pair_is_complete(self) -> SentryLocationUpdate:
        """Reject a body carrying only one coordinate — see `SentryLocation`."""
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be set together, or both left empty.")
        return self
