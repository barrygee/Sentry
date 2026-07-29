"""Frozen value types shared across the interfaces layer.

These carry no behaviour — pure data produced by adapters and consumed by
services. Keeping them dependency-free (no FastAPI, no SQLAlchemy) lets both
the hardware-edge adapters and the pure `identity` service import them
without pulling in unrelated layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class UsbDeviceSnapshot:
    """One USB device as observed at a single instant.

    Produced by `UsbDiscovery.enumerate()`. Fields mirror what is readable
    from Linux sysfs (`/sys/bus/usb/devices/*`) so the real adapter and its
    scripted test double share an identical shape.
    """

    topology_path: str
    """Bus-port.port.port, e.g. "1-1.4.2" — encodes the full hub tree."""

    bus_number: int
    """The USB bus number, e.g. 1."""

    port_chain: tuple[int, ...]
    """The port path as integers, e.g. (1, 4, 2) for "1-1.4.2"."""

    device_address: int
    """Kernel devnum. UNSTABLE across re-enumeration — display only, never a key."""

    vendor_id: str
    """Lowercase hex USB vendor ID with no "0x" prefix, e.g. "0bda"."""

    product_id: str
    """Lowercase hex USB product ID with no "0x" prefix, e.g. "2838"."""

    serial: str | None
    """The device's iSerial string, or None when the descriptor has none."""

    manufacturer: str | None
    """The device's iManufacturer string, or None when absent."""

    product: str | None
    """The device's iProduct string, or None when absent."""

    driver: str | None
    """The bound kernel driver name, e.g. "dvb_usb_rtl28xxu" (blacklist not
    applied) or "rtl2832u". None when no driver is bound."""

    sysfs_path: str
    """Absolute sysfs path this snapshot was read from. Diagnostics only."""


@dataclass(frozen=True, slots=True)
class HotplugEvent:
    """A single USB add/remove notification.

    Emitted by any `HotplugSource` implementation — the real udev-netlink
    listener, the sysfs-diff reconcile sweep, or their composite.
    """

    action: Literal["add", "remove"]
    """Whether the device newly appeared or newly disappeared."""

    topology_path: str
    """The affected device's bus-port path, matching `UsbDeviceSnapshot.topology_path`."""

    source: Literal["udev", "reconcile"]
    """Which mechanism observed this event, surfaced in `GET /api/health`."""

    observed_at_ms: int
    """Unix milliseconds when this event was observed."""


@dataclass(frozen=True, slots=True)
class PersistedDeviceRow:
    """One row of the `sdr_devices` table (architecture §6.1), decoupled from the ORM.

    This is the exact, frozen column list — the contract the database-engineer's
    SQLAlchemy model and repository (Phase 1B) must satisfy, and what
    `device_registry`/`port_allocator` depend on via `DeviceRepository`
    instead of importing SQLAlchemy directly.
    """

    id: int
    identity_kind: Literal["serial", "usb"]
    identity_key: str
    name: str
    description: str
    output_port: int
    enabled: bool
    center_hz: int | None
    sample_rate: int | None
    gain_db: float | None
    gain_auto: bool
    ppm_correction: int
    bias_tee: bool | None
    direct_sampling: int | None
    last_topology_path: str
    last_vendor_id: str
    last_product_id: str
    last_manufacturer: str
    last_product: str
    last_serial: str
    last_seen_at: int | None
    pending_replug_until: int | None
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class RtlSdrUsbStrings:
    """The USB descriptor strings librtlsdr reports for one enumerated index.

    Returned by `RtlSdrLibrary.usb_strings()`; matched against a
    `UsbDeviceSnapshot`'s `(serial, manufacturer, product)` to resolve the
    `-d <index>` argument for `rtl_tcp` at spawn time (architecture §5.3).
    """

    manufacturer: str
    """The device's manufacturer string as reported by librtlsdr."""

    product: str
    """The device's product string as reported by librtlsdr."""

    serial: str
    """The device's serial string as reported by librtlsdr (may be a factory default)."""
