"""`/api/config` — export and import a whole Sentry instance's configuration.

The point of this file is standing up a second Pi quickly: export from a working
Sentry, import into a fresh one, and its dongles come up already named, ported
and published exactly as the first one's are.

**The hotspot passphrase travels one way: in, never out.**

A config file is the single most copied, emailed and committed artefact a project
has, and `GET /api/config` is reachable by anyone who can reach the API. WiFi
credentials in an *exported* file would therefore leak by default, so the export
carries only `passphrase_set` — enough for an operator to see that a password
exists on the source, never the password itself.

An *import* may carry one. `HotspotConfigEntry.passphrase` is declared
`exclude=True`, so Pydantic parses it inbound and drops it from every dump
outbound: the field cannot appear in a file Sentry produced, and there is no
"remember to strip the password" branch anywhere to forget. Hand-adding it to a
provisioning file you control is a deliberate act with a deliberate blast radius;
having it fall out of a routine export is not. Setting one this way is still
gated on `apply_hotspot` and on the same auth token every other hotspot mutation
requires.

**The deploy-time gates are absent entirely**
(`SENTRY_HOTSPOT_CONTROL_ENABLED`, `SENTRY_AUTH_TOKEN`).
Those live in `.env` because they are the controls that require shell access to
the Pi (ADR-0007). A config file that could turn on host-network control, or set
the API's own credential, would hand exactly that away to anyone who can reach
the API — which is unauthenticated by default. They stay out of both this file
and the UI's editable surface. Note the asymmetry that makes the passphrase
acceptable and these not: a password lets someone onto a network whose API is
already token-guarded, whereas these two *are* the guard.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.backend.schemas.device import (
    DeviceVisibility,
    DirectSamplingMode,
    IdentityKind,
)
from app.backend.schemas.hotspot import HotspotBand, HotspotSecurity, validate_passphrase

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
    """The hotspot's shape. Its secret travels one way only — in.

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
    passphrase: SecretStr | None = Field(
        default=None,
        exclude=True,
        description=(
            "Write-only: hand-added to a provisioning file to set the destination's "
            "hotspot password. Never present in an exported file"
        ),
    )
    """The one credential this file may carry, and only inwards.

    `exclude=True` is the whole guarantee, and it is structural rather than a
    convention someone has to remember: Pydantic parses this field on the way in
    and omits it from every `model_dump`/`model_dump_json` on the way out. The
    export path builds a `HotspotConfigEntry` like any other, so there is no
    separate "remember not to include the password" branch to forget — a file
    Sentry produced cannot contain one, however it was produced.

    That asymmetry is the point. Exports are the artefact that gets copied,
    emailed and committed; a hand-written provisioning file is one an operator
    made deliberately and controls. Setting a password this way still needs
    `apply_hotspot` opted into, and still passes the auth-token gate that every
    other hotspot mutation does.

    `SecretStr` so it cannot leak through a log line, a traceback or a
    validation error that echoes the model back.
    """

    @field_validator("passphrase")
    @classmethod
    def _check_passphrase(cls, passphrase: SecretStr | None) -> SecretStr | None:
        """Reject a password the AP could never accept, at parse time.

        The same rule `PUT /api/hotspot` applies. Without it an 8-character
        minimum would fail deep inside `nmcli` during an import, reported as a
        profile-write failure rather than as the typo it is.
        """
        if passphrase is None:
            return None
        validate_passphrase(passphrase.get_secret_value())
        return passphrase


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
