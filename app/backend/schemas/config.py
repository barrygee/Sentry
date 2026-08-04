"""`/api/config` — export and import a whole Sentry instance's configuration.

The point of this file is standing up a second Pi quickly: export from a working
Sentry, import into a fresh one, and its dongles come up already named, ported
and published exactly as the first one's are.

**Two things are deliberately absent, and both absences are load-bearing.**

*The hotspot passphrase.* A config file is the single most copied, emailed and
committed artefact a project has. WiFi credentials in one would leak by default.
The export carries `passphrase_set` so an operator can see a password exists, and
importing never sets one — a fresh instance asks for it once, in the UI.

*The deploy-time gates* (`SENTRY_HOTSPOT_CONTROL_ENABLED`, `SENTRY_AUTH_TOKEN`).
Those live in `.env` because they are the controls that require shell access to
the Pi (ADR-0007). A config file that could turn on host-network control, or set
the API's own credential, would hand exactly that away to anyone who can reach
the API — which is unauthenticated by default. They stay out of both this file
and the UI's editable surface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.backend.schemas.device import (
    DeviceVisibility,
    DirectSamplingMode,
    IdentityKind,
)
from app.backend.schemas.hotspot import HotspotBand, HotspotSecurity

CONFIG_VERSION: Literal[1] = 1
"""Bumped only on a breaking change to this file's shape.

An import refuses a version it does not recognise rather than guessing, so a
file written by a newer Sentry cannot be half-applied by an older one.
"""


class DeviceConfigEntry(BaseModel):
    """One device's operator-set configuration, keyed by its stable identity.

    Deliberately keyed by `(identity_kind, identity_key)` rather than
    `device_id` or `record_id`: the row id is local to one instance and means
    nothing on another Pi, whereas the identity is the same fact about the same
    physical dongle wherever it is plugged in (ADR-0003).
    """

    model_config = ConfigDict(extra="forbid")

    identity_kind: IdentityKind
    identity_key: str
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=256)
    notes: str = Field(default="", max_length=2000)
    antenna: str = Field(default="", max_length=120)
    output_port: int | None = Field(default=None, ge=1024, le=65533)
    enabled: bool = False
    visibility: DeviceVisibility = "private"
    center_hz: int | None = Field(default=None, ge=24_000_000, le=1_766_000_000)
    sample_rate: int | None = None
    gain_db: float | None = Field(default=None, ge=0.0, le=50.0)
    gain_auto: bool = True
    ppm_correction: int = Field(default=0, ge=-200, le=200)
    bias_tee: bool | None = None
    direct_sampling: DirectSamplingMode | None = None


class HotspotConfigEntry(BaseModel):
    """The hotspot's shape, minus its secret.

    `passphrase_set` is reported so an operator importing this file knows
    whether the source instance had one, and therefore whether the destination
    will need a password typing in before the hotspot can start. It is never
    a credential and never round-trips one.
    """

    model_config = ConfigDict(extra="forbid")

    ssid: str | None = None
    hidden: bool = True
    security: HotspotSecurity = "wpa2"
    band: HotspotBand = "bg"
    channel: int = Field(default=0, ge=0, le=196)
    gateway_cidr: str | None = None
    interface: str | None = None
    enabled: bool = Field(
        default=False, description="Whether the source instance had the hotspot starting on boot"
    )
    passphrase_set: bool = Field(
        default=False,
        description="Whether the source had a password stored. Never the password itself",
    )


class SentryConfig(BaseModel):
    """The whole exportable configuration of one Sentry instance."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    comment: str = Field(
        default="",
        alias="_comment",
        description="Free-text note carried in the file and otherwise ignored",
    )
    """Accepted so a hand-written or shipped example can explain itself in the file.

    JSON has no comment syntax, and `extra="forbid"` — which is what stops an
    operator's typo being silently dropped — would otherwise reject any file
    carrying one. Declaring the single key explicitly keeps every *other*
    unknown field an error, which is the behaviour worth having.
    """

    version: int = Field(
        default=CONFIG_VERSION, description="Config-file format version, not the app version"
    )
    """Deliberately a plain `int` rather than `Literal[1]`.

    Pinning the literal would have Pydantic reject an unknown version with its
    own list-shaped 422 before the router could say anything useful. The whole
    point of a version field is telling an operator holding a file from a newer
    Sentry *why* it will not load, so the check lives in the router and answers
    in the uniform `{"detail": {"code", "message"}}` envelope.
    """
    generated_at: int = Field(default=0, description="Unix ms the file was exported")
    sentry_version: str = Field(default="", description="The app version that wrote it")
    devices: tuple[DeviceConfigEntry, ...] = ()
    hotspot: HotspotConfigEntry | None = None


class ConfigImportRequest(BaseModel):
    """`POST /api/config` body — a previously exported file, optionally narrowed."""

    model_config = ConfigDict(extra="forbid")

    config: SentryConfig
    apply_devices: bool = Field(default=True, description="Apply the file's device configuration")
    apply_hotspot: bool = Field(
        default=False,
        description=(
            "Apply the file's hotspot settings. Off by default: it can change which "
            "network this Pi serves, and never carries a password to start it with"
        ),
    )


class DeviceImportOutcome(BaseModel):
    """What happened to one device entry during an import."""

    model_config = ConfigDict(frozen=True)

    identity_kind: IdentityKind
    identity_key: str
    outcome: Literal["applied", "skipped", "failed"]
    detail: str = Field(default="", description="Why it was skipped or how it failed")


class ConfigImportResult(BaseModel):
    """`POST /api/config` response — a per-entry report, not just a status code.

    An import is partial by nature: a port in the file may already be taken on
    this Pi, or a dongle may not be plugged in yet. Reporting each entry lets an
    operator see exactly what landed rather than inferring it from a device list.
    """

    model_config = ConfigDict(frozen=True)

    devices: tuple[DeviceImportOutcome, ...] = ()
    devices_applied: int = Field(default=0, ge=0)
    devices_skipped: int = Field(default=0, ge=0)
    devices_failed: int = Field(default=0, ge=0)
    hotspot_applied: bool = False
    hotspot_detail: str = Field(
        default="", description="Why the hotspot was not applied, when it was not"
    )
    generated_at: int = Field(default=0, description="Unix ms")
