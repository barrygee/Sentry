"""SQLAlchemy 2.0 declarative models for Sentry's persisted state (architecture §6).

There is exactly one table: `sdr_devices`. It holds **operator intent**, not
observed reality — a detected-but-unconfigured device lives only in memory
(`device_registry`); a row's existence here means "the operator configured
this device". Column names and types mirror `interfaces.types.PersistedDeviceRow`
exactly, since that frozen dataclass is the contract the rest of the backend
(via `interfaces.repository.DeviceRepository`) depends on.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index
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

    output_port: Mapped[int] = mapped_column(nullable=False)
    """The relay's public IQ port `P`; `P + 2` is implicitly reserved for the
    NDJSON control channel (architecture §8) and is never stored separately."""

    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="1")
    """Whether the supervisor should run this device's rtl_tcp+relay pair."""

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
    )
