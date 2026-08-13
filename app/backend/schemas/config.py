"""`/api/config` — export and import a whole Sentry instance's configuration.

The point of this file is standing up a second Pi quickly: export from a working
Sentry, import into a fresh one, and its dongles come up already named, ported
and published exactly as the first one's are.

**One section is not like the others.** `location` describes where the exporting
box physically sits, not how it is configured, so applying it to a *different*
Pi is usually wrong even though applying every other section is right. It is
carried anyway — a rebuilt Pi should come back on the map without anyone
retyping coordinates — and gated behind `apply_location` for the cloning case.
See `SentryConfig.location`.

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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
    model_validator,
)

from app.backend.schemas.device import (
    DeviceVisibility,
    DirectSamplingMode,
    IdentityKind,
)
from app.backend.schemas.hotspot import HotspotBand, HotspotSecurity, validate_passphrase
from app.backend.schemas.location import (
    MAXIMUM_LATITUDE,
    MAXIMUM_LONGITUDE,
    MINIMUM_LATITUDE,
    MINIMUM_LONGITUDE,
)
from app.backend.services.console_auth import MINIMUM_PASSWORD_LENGTH

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


class LocationConfigEntry(BaseModel):
    """The file's fixed-position section, whose unset coordinates are `""` on the wire.

    Internally these stay `float | None`, which is what every other layer already
    speaks; the empty string exists only in JSON. Two conversions bridge the gap:
    `_empty_string_is_no_value` on the way in, `_serialise` on the way out.

    The empty string rather than `null` is deliberate, and it is about the file
    being *hand-editable*. A config file is the artefact an operator opens in a
    text editor to fill in, and `"latitude": ""` is an obvious blank waiting for
    a number, where `null` reads as a value someone chose and `"latitude"`
    missing altogether reads as a key you would have to know to add.

    Both coordinates or neither, and both within range — the same rules
    `PUT /api/location` applies, enforced here so a hand-edited file fails at
    parse time with a message about the field rather than deep inside an import.
    """

    model_config = ConfigDict(extra="forbid")

    latitude: float | None = Field(
        default=None,
        ge=MINIMUM_LATITUDE,
        le=MAXIMUM_LATITUDE,
        description='Decimal degrees, or "" when no position is set',
    )
    longitude: float | None = Field(
        default=None,
        ge=MINIMUM_LONGITUDE,
        le=MAXIMUM_LONGITUDE,
        description='Decimal degrees, or "" when no position is set',
    )

    @property
    def is_set(self) -> bool:
        """Whether this section carries a plottable position."""
        return self.latitude is not None and self.longitude is not None

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def _empty_string_is_no_value(cls, value: object) -> object:
        """Read `""` (and a whitespace-only field) back as "no position".

        `mode="before"` so it runs ahead of the float coercion that would
        otherwise reject the very string this model exports. Whitespace is
        folded in because a hand-edited file is the expected input here, and
        `"latitude": " "` is the same intent as `""` typed slightly worse.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_serializer("latitude", "longitude")
    def _serialise(self, value: float | None) -> float | str:
        """Write an unset coordinate as `""` rather than `null`."""
        return "" if value is None else value

    @model_validator(mode="after")
    def _check_pair_is_complete(self) -> LocationConfigEntry:
        """Refuse half a position — the same rule `SentryLocation` applies."""
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be set together, or both left empty.")
        return self


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

    location: LocationConfigEntry | None = Field(
        default=None,
        description=(
            "The exporting Sentry's fixed position. Always written on export, with "
            "empty strings when none is set. Absent entirely in a pre-location file"
        ),
    )
    """This Sentry's coordinates, so a rebuilt Pi comes back on the map by itself.

    **Read this before importing onto a second Pi.** Unlike everything else in
    this file, a location is not a property of the *configuration* — it is a
    property of *where the box physically sits*. Cloning a working Sentry onto
    a second one and applying this section puts machine two's marker on top of
    machine one's, on every Sentinel watching, until somebody notices two
    Sentries at one address. That is why the import is gated on
    `apply_location`, which an operator restoring a backup leaves alone and an
    operator provisioning a *new* Pi turns off.

    Optional here, but always present in a file Sentry wrote: `None` means the
    key was *absent*, which only happens in a file exported before this section
    existed. An export instead writes the section with `""` in both coordinates
    when no position is set (see `LocationConfigEntry`), which is what makes the
    file readable as a template — the keys are visibly there to be filled in
    rather than something an operator has to know to add.
    """

    console_password: SecretStr | None = Field(
        default=None,
        exclude=True,
        description=(
            "Write-only: hand-added to a provisioning file to set the controller's "
            "password. Never present in an exported file"
        ),
    )
    """The second credential this file may carry inwards, and only inwards.

    Same mechanism and same reasoning as `HotspotConfigEntry.passphrase`:
    `exclude=True` means Pydantic parses it on the way in and drops it from
    every dump on the way out, so a file Sentry produced cannot contain one
    however it was produced.

    It exists because provisioning a Pi should not require a second, manual step
    that is the one an operator is most likely to skip. A fresh controller is
    open until a password is set, so an import that configures everything *but*
    the password leaves the machine reachable by anyone — which is the outcome
    the prompt-on-every-visit design is already trying to avoid.

    Applied only when it would not lock the operator out of a controller that
    already has one: see `_import_console_password` in `routers/config.py`.
    """

    @field_validator("console_password")
    @classmethod
    def _check_console_password(cls, password: SecretStr | None) -> SecretStr | None:
        """Reject a password the API would refuse, at parse time rather than mid-import."""
        if password is None:
            return None
        if len(password.get_secret_value()) < MINIMUM_PASSWORD_LENGTH:
            raise ValueError(
                f"console_password must be at least {MINIMUM_PASSWORD_LENGTH} characters."
            )
        return password


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
    apply_location: bool = Field(
        default=True,
        description=(
            "Apply the file's fixed position. On by default — restoring a Pi is the "
            "common case; turn it off when provisioning a second Pi from the first's file"
        ),
    )
    """On by default, unlike `apply_hotspot`, because the two fail in opposite directions.

    A wrongly-applied hotspot changes which network the Pi serves and can cut
    the operator off from it; a wrongly-applied location puts a marker in the
    wrong place on a map, which is visible, harmless and fixed by typing the
    right numbers in. Defaulting the recoverable one to *on* is what makes
    restoring a backup a single action rather than a checklist.
    """


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
    console_password_applied: bool = False
    console_password_detail: str = Field(
        default="", description="Why the controller password was not set, when it was not"
    )
    location_applied: bool = False
    location_detail: str = Field(
        default="", description="Why the position was not applied, when it was not"
    )
    generated_at: int = Field(default=0, description="Unix ms")
