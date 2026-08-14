"""SQLAlchemy 2.0 declarative models for Sentry's persisted state (architecture §6).

`sdr_devices` holds **operator intent**, not
observed reality — a detected-but-unconfigured device lives only in memory
(`device_registry`); a row's existence here means "the operator configured
this device". Column names and types mirror `interfaces.types.PersistedDeviceRow`
exactly, since that frozen dataclass is the contract the rest of the backend
(via `interfaces.repository.DeviceRepository`) depends on.

`console_auth` holds the console password (ADR-0010) and is deliberately
separate rather than a column on anything: it is credential material with a
different lifecycle, different access pattern, and a very different
consequence if it is ever accidentally serialised alongside device data.

`device_reservations` holds live claims on dongles — a lease with an expiry,
kept apart from device configuration because the two have different lifecycles:
configuration is what the operator wants indefinitely, a lease is true for the
next two minutes.

`host_control_settings` and `sentry_location` are single-row instance settings,
each kept separate for the same reason: they are different *kinds* of fact
(what this host is allowed to do, and where this host physically is), and one
wide "settings" table would make both harder to reason about than either.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The declarative base every Sentry ORM model inherits from.

    `alembic/env.py` imports `Base.metadata` as `target_metadata` so
    autogenerate and the initial migration stay in lockstep with these models.
    """


class SdrDeviceModel(Base):
    """One persisted RTL-SDR device configuration row (architecture §6.1).

    Keyed by the resolved device identity — `(identity_kind, identity_key)` —
    rather than by USB enumeration order or kernel devnum, both of which are
    unstable across a reboot or replug (architecture §5). The surrogate
    integer `id` exists only for internal foreign-keying and is never exposed
    as the API's public device key.
    """

    __tablename__ = "sdr_devices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """Internal surrogate key. Never the public `device_id` (architecture §7 intro)."""

    identity_kind: Mapped[str] = mapped_column(nullable=False)
    """Which persistence-key tier this row is keyed by: "serial" or "usb" (architecture §5.1)."""

    identity_key: Mapped[str] = mapped_column(nullable=False)
    """The serial value (tier 1) or USB topology path (tier 2), e.g. "1-1.4.2"."""

    name: Mapped[str] = mapped_column(nullable=False)
    """Operator-assigned label, e.g. "ADSB SDR". 1-64 characters, enforced by both
    the Pydantic edge validator and the `ck_sdr_devices_name_length` CHECK."""

    description: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Free-text note, exported to Sentinel. Empty string, never NULL."""

    notes: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """The operator's free-text notes — siting problems, who owns the dongle, what
    still needs fixing. Longer and more free-form than `description`, and like it,
    exported to Sentinel for any device the operator publishes. Empty string,
    never NULL."""

    antenna: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Operator-recorded antenna description, e.g. "Discone, loft". Exported to
    Sentinel alongside the rest of the device. Empty string, never NULL."""

    output_port: Mapped[int] = mapped_column(nullable=False)
    """The relay's public IQ port `P`; `P + 2` is implicitly reserved for the
    NDJSON control channel (architecture §8) and is never stored separately."""

    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="1")
    """Whether the supervisor should run this device's rtl_tcp+relay pair."""

    visibility: Mapped[str] = mapped_column(
        nullable=False, default="private", server_default="private"
    )
    """Whether this device is published in `GET /api/v1/sdrs`: "public" lists it
    for any Sentinel that queries the export, "private" omits it entirely.
    Defaults to "private" so a newly configured dongle is never published by an
    operator who simply never visited the toggle — sharing is opt-in, since
    what the export hands out is a reachable IQ endpoint, not just a name."""

    center_hz: Mapped[int | None] = mapped_column(nullable=True)
    """Startup tuning frequency in Hz. NULL defers to the relay's built-in default."""

    sample_rate: Mapped[int | None] = mapped_column(nullable=True)
    """Startup sample rate in Hz. NULL defers to the relay's built-in default."""

    gain_db: Mapped[float | None] = mapped_column(nullable=True)
    """Startup tuner gain in dB. NULL defers to the relay's built-in default."""

    gain_auto: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="1")
    """Whether the tuner runs in automatic-gain-control mode."""

    ppm_correction: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    """Crystal frequency correction in parts-per-million, passed as `rtl_tcp -P`."""

    bias_tee: Mapped[bool | None] = mapped_column(nullable=True)
    """Bias-T power state, when the dongle supports it. NULL when not configured/unknown."""

    direct_sampling: Mapped[int | None] = mapped_column(nullable=True)
    """Direct-sampling mode for `rtl_tcp -D` (0=off, 1=I-ADC, 2=Q-ADC). NULL when unset."""

    last_topology_path: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Last-seen USB bus-port path, even for serial-keyed rows, so an absent
    device can still say "was in port 1-1.4.2" in the UI."""

    last_vendor_id: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Cached lowercase-hex USB vendor ID, so an absent device still renders."""

    last_product_id: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Cached lowercase-hex USB product ID, so an absent device still renders."""

    last_manufacturer: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Cached iManufacturer string, so an absent device still renders."""

    last_product: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Cached iProduct string, so an absent device still renders."""

    last_serial: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """The raw reported serial, even for a tier-2 (USB-topology-keyed) row."""

    last_seen_at: Mapped[int | None] = mapped_column(nullable=True)
    """Unix milliseconds this device was last observed present. NULL if never seen."""

    pending_replug_until: Mapped[int | None] = mapped_column(nullable=True)
    """Unix milliseconds until which a missing-device alarm is suppressed after
    an EEPROM serial flash (architecture §7.6). NULL when no flash is pending."""

    created_at: Mapped[int] = mapped_column(nullable=False)
    """Unix milliseconds this row was first created."""

    updated_at: Mapped[int] = mapped_column(nullable=False)
    """Unix milliseconds this row was last modified."""

    __table_args__ = (
        Index(
            "ux_sdr_devices_identity",
            "identity_kind",
            "identity_key",
            unique=True,
        ),
        Index("ux_sdr_devices_port", "output_port", unique=True),
        CheckConstraint(
            "identity_kind IN ('serial', 'usb')",
            name="ck_sdr_devices_identity_kind",
        ),
        CheckConstraint(
            "output_port BETWEEN 1024 AND 65533",
            name="ck_sdr_devices_output_port_range",
        ),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 64",
            name="ck_sdr_devices_name_length",
        ),
        CheckConstraint(
            "visibility IN ('public', 'private')",
            name="ck_sdr_devices_visibility",
        ),
    )


class DeviceReservationModel(Base):
    """A live claim on one dongle, held by a consumer that is using it.

    A dongle is a single physical resource with several possible consumers —
    Sentinel's AIR view, its voice decoder, a second Sentinel, or an operator in
    this console. Any of them can retune it out from under the others, and the
    one that loses simply stops decoding without being told why. A reservation
    makes "this device is busy, and here is who has it" a fact the API can
    enforce and every consumer can see.

    **A reservation is a lease, not a flag.** `expires_at` is the whole design.
    Every explicit-release path — a browser tab closed, a container killed, a
    network partitioned, a laptop asleep — fails open into "locked for ever"
    without it, and recovering would mean an operator finding a row in a
    database. A holder renews for as long as it is still using the device;
    stopping is how it lets go, whether it meant to or not.

    Deliberately its own table rather than columns on `sdr_devices`, for the
    reason `console_auth` and `sentry_location` are: a lease has a different
    lifecycle from device configuration. Configuration is what the operator
    wants to be true indefinitely; a lease is true for the next two minutes.
    Keeping them apart also leaves `PersistedDeviceRow` — the frozen contract
    the repository and registry are written against — untouched.

    Keyed by `(identity_kind, identity_key)` rather than the surrogate device
    row id, so a claim is on the *physical dongle* (ADR-0003) and means the same
    thing across a replug, and so a device with no configuration row yet can
    still be claimed.
    """

    __tablename__ = "device_reservations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    identity_kind: Mapped[str] = mapped_column(nullable=False)
    """Which identity tier this claim is keyed by: "serial" or "usb"."""

    identity_key: Mapped[str] = mapped_column(nullable=False)
    """The serial value or USB topology path identifying the claimed dongle."""

    holder: Mapped[str] = mapped_column(nullable=False)
    """Opaque consumer id, e.g. `sentinel:<instance-uuid>`.

    Opaque on purpose: Sentry does not need to understand who its consumers are
    to arbitrate between them, and a closed vocabulary here would need changing
    every time something new wanted a dongle.
    """

    label: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    """Operator-facing description, e.g. "Sentinel — AIR (ADS-B)".

    Separate from `holder` because the two answer different questions: the
    console shows this, and a machine matches on that. Without it the UI would
    have to render a UUID at an operator and hope they recognised it.
    """

    reserved_at: Mapped[int] = mapped_column(nullable=False, default=0)
    """Unix ms the claim was first taken. Not moved by a renewal, so the UI can
    say how long a consumer has held a device rather than how recently it
    checked in."""

    expires_at: Mapped[int] = mapped_column(nullable=False, default=0)
    """Unix ms the lease lapses unless renewed. The safety property; see above."""

    __table_args__ = (
        # One live claim per dongle, enforced by the database rather than by the
        # service remembering to check. Two consumers racing to claim the same
        # device is exactly the situation this table exists for, so the losing
        # write must fail rather than quietly become the second row.
        UniqueConstraint("identity_kind", "identity_key", name="uq_device_reservations_identity"),
    )


class ConsoleAuthModel(Base):
    """The console password and the state that governs its sessions (ADR-0010).

    A single row, id 1, created by the migration so no code path has to decide
    whether it exists. `password_hash` being `NULL` is the meaningful state:
    it means no password has been set and the console is open, which is the
    documented default for a fresh install rather than an error.

    The hash is argon2id. The plaintext is never stored, never logged, and
    never leaves the request that set it.
    """

    __tablename__ = "console_auth"

    id: Mapped[int] = mapped_column(primary_key=True)
    """Always 1. A single-row table, constrained below rather than by convention."""

    password_hash: Mapped[str | None] = mapped_column(nullable=True, default=None)
    """argon2id hash, or `NULL` when no password is set and the console is open."""

    password_version: Mapped[int] = mapped_column(nullable=False, default=0)
    """Incremented whenever the password changes.

    Signed into every session cookie and checked on every request, which is what
    makes changing the password log out every existing session — including one
    on a device the operator no longer has. Without it, changing a password
    would secure future logins while leaving present sessions untouched, which
    is the opposite of what someone changing a password after a scare expects.
    """

    session_secret: Mapped[str] = mapped_column(nullable=False)
    """Random key the session cookie's signature is derived from.

    Generated once by the migration. Rotating it invalidates every session, so
    it is the emergency lever the password-reset path pulls.
    """

    updated_at: Mapped[int] = mapped_column(nullable=False, default=0)
    """Unix ms the password last changed. Displayed; never used for auth decisions."""

    __table_args__ = (CheckConstraint("id = 1", name="ck_console_auth_single_row"),)


class HostControlSettingsModel(Base):
    """Host-capability switches an operator can flip from the UI (ADR-0013).

    A single row, like `console_auth`. Holds the settings that used to be
    deploy-time `.env` gates and are now operator-facing, because requiring a
    terminal to turn on a feature the UI otherwise fully manages made the UI's
    own instructions the product.

    Only `hotspot_control_enabled` lives here so far. The bar for adding a
    setting is that flipping it must be safe for whoever can reach the console —
    which is why the hotspot toggle is refused while no console password is set
    (ADR-0013), not merely hidden.
    """

    __tablename__ = "host_control_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    """Always 1. A single-row table, constrained below rather than by convention."""

    hotspot_control_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="0"
    )
    """Whether the API may reconfigure this host's WiFi (ADR-0007, ADR-0013).

    `False` on a fresh install, which is the same default `SENTRY_HOTSPOT_CONTROL_ENABLED`
    always had — what changed is who can flip it, not what it starts as.
    """

    updated_at: Mapped[int] = mapped_column(nullable=False, default=0)
    """Unix ms this row last changed. Displayed; never used for an auth decision."""

    __table_args__ = (CheckConstraint("id = 1", name="ck_host_control_settings_single_row"),)


class SentryLocationModel(Base):
    """This Sentry's fixed geographic position, as the operator typed it.

    A single row, like `console_auth` and `host_control_settings`. It exists so
    a Sentinel can plot the Pi on a map without anybody having to tell Sentinel
    separately where the Pi is — the coordinates travel with the device list
    Sentinel already fetches.

    Deliberately *not* a column on `host_control_settings`. That table is the
    host-capability switches (ADR-0013), where the bar for a new setting is that
    flipping it must be safe for whoever can reach the console. A latitude is
    not a capability, and folding it in would blur a table whose whole purpose
    is being the place where dangerous switches live.

    Both coordinates are nullable and start that way. "Unset" is a real state —
    a Sentry whose operator has not placed it yet must be distinguishable from
    one sitting at 0°N 0°E in the Gulf of Guinea, or every fresh install plots
    itself onto Null Island.
    """

    __tablename__ = "sentry_location"

    id: Mapped[int] = mapped_column(primary_key=True)
    """Always 1. A single-row table, constrained below rather than by convention."""

    latitude: Mapped[float | None] = mapped_column(nullable=True, default=None)
    """Decimal degrees, -90..90. `None` means the operator has not set a position."""

    longitude: Mapped[float | None] = mapped_column(nullable=True, default=None)
    """Decimal degrees, -180..180. `None` means the operator has not set a position."""

    updated_at: Mapped[int] = mapped_column(nullable=False, default=0)
    """Unix ms this row last changed. Displayed; never used for an auth decision."""

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_sentry_location_single_row"),
        # Rejected at the storage layer as well as in the schema. The API is not
        # the only writer — a migration, a repair script or a future importer
        # could all reach this row, and a longitude of 900 silently stored is a
        # marker dropped somewhere impossible on every Sentinel watching.
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90.0 AND latitude <= 90.0)",
            name="ck_sentry_location_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180.0 AND longitude <= 180.0)",
            name="ck_sentry_location_longitude_range",
        ),
    )
