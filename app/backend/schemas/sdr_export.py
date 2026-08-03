"""`GET /api/v1/sdrs` — the versioned, additive-only Sentinel contract (architecture §7.7).

This is the only surface Sentinel consumes. It is published by Sentry alone;
the Sentinel-side import is explicitly out of scope for this repository
(decision 4) and lands as a follow-up in the Sentinel project.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SDR_EXPORT_API_VERSION = 1
"""Value of `api_version` and the `X-Sentry-Sdr-Api-Version` response header."""


class SdrExportSource(BaseModel):
    """Identifies the Sentry instance that produced this export."""

    model_config = ConfigDict(frozen=True)

    name: Literal["sentry"] = "sentry"
    version: str
    host: str = Field(description="Never 0.0.0.0 or a container-internal address")
    http_port: int


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
