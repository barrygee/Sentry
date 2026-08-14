"""`GET /api/v1/sdrs` — the versioned, additive-only Sentinel contract (architecture §7.7).

This is the only surface Sentinel consumes. It is published by Sentry alone;
the Sentinel-side import is explicitly out of scope for this repository
(decision 4) and lands as a follow-up in the Sentinel project.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.backend.schemas.location import SentryLocation

SDR_EXPORT_API_VERSION = 1
"""Value of `api_version` and the `X-Sentry-Sdr-Api-Version` response header."""


class SdrExportSource(BaseModel):
    """Identifies the Sentry instance that produced this export."""

    model_config = ConfigDict(frozen=True)

    name: Literal["sentry"] = "sentry"
    version: str
    host: str = Field(description="Never 0.0.0.0 or a container-internal address")
    http_port: int
    location: SentryLocation = Field(
        default_factory=SentryLocation,
        description="This Sentry's fixed position; both coordinates null when unset",
    )
    """Where this Sentry physically is, so Sentinel can plot it.

    Belongs on `source` rather than on each `SdrExportItem`: it is a fact about
    the instance, not about a dongle, and four devices in one box would
    otherwise repeat the same coordinates four times and invite them drifting
    apart.

    Additive within api_version 1 — a consumer that does not know the key is
    unaffected, and one that does gets a plottable Sentry from the same single
    call that gives it the device list. Note this endpoint is unauthenticated
    (ADR-0010), so the position is readable by anyone who can reach the Pi; see
    `schemas/location.py`.
    """


class SdrExportItem(BaseModel):
    """One configured device, mapped onto Sentinel's `SdrRadio` / `RadioIn` field names.

    Field-by-field mapping and rationale: architecture §7.8.
    """

    model_config = ConfigDict(frozen=True)

    sentry_device_id: str = Field(description="Idempotency key for Sentinel's import")
    name: str
    host: str
    port: int = Field(description="The relay's IQ port P")
    control_port: int = Field(description="P + 2, sent for verification only")
    description: str
    notes: str = Field(default="", description="The operator's free-text notes for this device")
    antenna: str = Field(default="", description="The operator-recorded antenna, or empty")
    enabled: bool
    bandwidth: int | None = Field(default=None, description="Sentry's sample_rate")
    rf_gain: float | None = Field(default=None, description="Sentry's gain_db; null when AGC")
    agc: bool | None = Field(default=None, description="Sentry's gain_auto")
    available: bool = Field(description="Display-only: grey out rather than hide when false")
    state: str = Field(description="Display-only device state")
    reserved_by: str | None = Field(
        default=None, description="Consumer currently holding this device, or null when free"
    )
    reserved_label: str = Field(
        default="", description='Operator-facing holder name, e.g. "Sentinel — AIR (ADS-B)"'
    )
    reserved_until: int | None = Field(
        default=None, description="Unix ms the holder's lease lapses unless renewed"
    )
    """Who has this dongle, so a *second* Sentinel can see it is taken.

    Without it, two Sentinels both wanting the same device would each discover
    the conflict only by trying to claim it and being refused — which works, but
    means the UI can never show "in use by …" until the operator has already
    asked for it. Additive within api_version 1: a consumer that does not know
    these keys is unaffected.

    `reserved_until` is published as well as the holder because a lease that is
    about to lapse and one just renewed are different situations to a consumer
    deciding whether to wait.
    """


class SdrExportResponse(BaseModel):
    """`GET /api/v1/sdrs` and `GET /api/sdrs` (permanent alias) body."""

    model_config = ConfigDict(frozen=True)

    api_version: int = SDR_EXPORT_API_VERSION
    generated_at: int
    source: SdrExportSource
    control_port_offset: int = Field(
        default=2, description="Sentinel already computes port + this offset"
    )
    sdrs: tuple[SdrExportItem, ...] = Field(
        description="Only devices the operator marked public; private ones are omitted"
    )
