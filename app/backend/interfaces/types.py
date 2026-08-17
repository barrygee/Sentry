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
    notes: str
    antenna: str
    output_port: int
    enabled: bool
    visibility: Literal["public", "private"]
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


HotspotSecurity = Literal["wpa2", "wpa3"]
"""WPA2-Personal (`wpa-psk`) or WPA3-Personal/SAE (`sae`). Both are pre-shared-key
schemes with no username — a username would require WPA-Enterprise and a RADIUS
server, which Sentry deliberately does not offer (ADR-0007)."""

HotspotBand = Literal["bg", "a"]
"""NetworkManager's `802-11-wireless.band` values: `bg` is 2.4 GHz, `a` is 5 GHz."""


@dataclass(frozen=True, slots=True)
class WirelessInterface:
    """One wireless network interface as the host's NetworkManager reports it.

    Produced by `WifiApController.list_wireless_interfaces()`. Everything here
    is observational: the service uses it to choose an access-point interface
    and, critically, to refuse one that is currently carrying the host's own
    connectivity (ADR-0007 — the hotspot is strictly additive and must never
    silently drop an existing link).
    """

    name: str
    """The kernel interface name, e.g. "wlan0"."""

    mac_address: str | None
    """The interface's hardware address, or None when NetworkManager did not report one."""

    supports_ap: bool | None
    """Whether the driver advertises access-point mode.

    `None` means the installed `nmcli` did not report the capability at all —
    the field is version-dependent. Callers must treat `None` as "assume
    capable" and let activation fail loudly, rather than refusing up front and
    making the feature unusable on an older NetworkManager.
    """

    state: str
    """NetworkManager's device state verbatim, e.g. "connected", "disconnected"."""

    active_connection_name: str | None
    """The NM profile currently active on this interface, or None when idle.

    Non-None means bringing an access point up here would tear that connection
    down — the condition the service refuses without explicit confirmation.
    """

    station_ssid: str | None
    """The SSID this interface is joined to as a client, when it is one.

    Named in the operator-facing warning so they know exactly which network
    they are about to drop.
    """

    ipv4_addresses: tuple[str, ...]
    """Every IPv4 address currently assigned, in CIDR form, e.g. ("192.168.1.45/24",)."""

    carries_default_route: bool
    """Whether the host's default route currently goes out of this interface.

    The strongest available signal that this interface *is* the uplink.
    """


@dataclass(frozen=True, slots=True)
class HotspotProfile:
    """The desired access-point configuration, minus its secret.

    **There is deliberately no passphrase field.** The pre-shared key is passed
    as a separate argument to `WifiApController.apply_profile()` and is never
    carried in a value type, so it cannot be reached by an accidental `repr()`,
    a log record, a serialized response, or a captured test double
    (ADR-0007 — the passphrase is write-only end to end).
    """

    ssid: str
    """The network name, 1-32 UTF-8 *bytes* (not characters)."""

    hidden: bool
    """Whether to suppress SSID broadcast. Defaults on for Sentry.

    Not a security control — it defeats casual scanning and nothing more. The
    pre-shared key is what protects the network.
    """

    security: HotspotSecurity
    """WPA2-Personal or WPA3-Personal."""

    band: HotspotBand
    """2.4 GHz or 5 GHz."""

    channel: int
    """The channel to use, or 0 to let the driver choose.

    A legal channel can still be unavailable in the host's regulatory domain,
    which surfaces as an activation failure rather than a validation error.
    """

    gateway_cidr: str
    """The address the Pi takes on the AP interface, e.g. "10.42.0.1/24".

    Pinned explicitly rather than left to NetworkManager's default, because
    this address is what a human types into Sentinel by hand and it must never
    move between activations.
    """

    interface: str
    """The wireless interface to raise the access point on, e.g. "wlan0"."""

    autoconnect: bool
    """Whether NetworkManager should bring this profile up on boot.

    Only ever set true once an operator has confirmed they can still reach the
    API with the hotspot running, so a configuration that locks everyone out
    cannot survive a reboot.
    """


@dataclass(frozen=True, slots=True)
class HotspotRuntimeState:
    """What the host's NetworkManager currently reports about Sentry's AP profile.

    Read back from NetworkManager rather than remembered, because the profile
    itself is the system of record — an operator editing it with `nmcli` on the
    Pi is a legitimate thing to do, and Sentry must show reality rather than a
    stale cache.
    """

    profile_exists: bool
    """Whether Sentry's connection profile is present at all."""

    active: bool
    """Whether the profile is currently up on its interface."""

    autoconnect: bool
    """Whether the profile is set to come up on boot."""

    interface: str | None
    """The interface the profile is bound to, or None when unset/absent."""

    ssid: str | None
    """The configured network name, or None when no profile exists."""

    hidden: bool
    """Whether SSID broadcast is suppressed."""

    security: HotspotSecurity
    """The configured key-management scheme."""

    band: HotspotBand
    """The configured band."""

    channel: int
    """The configured channel, 0 meaning automatic."""

    gateway_cidr: str | None
    """The configured AP-side address in CIDR form, or None when unset."""

    passphrase_set: bool
    """Whether a pre-shared key is stored — never the key itself.

    Derived from NetworkManager reporting the property as present; read without
    `--show-secrets`, so the value is never retrieved even internally.
    """

    activation_state: str | None
    """NetworkManager's activation state for the profile, for diagnostics."""


@dataclass(frozen=True, slots=True)
class HotspotClient:
    """One DHCP lease issued by the access point's dnsmasq instance.

    **A lease is not an association.** A client that walked out of range keeps
    its lease until expiry, and a statically-addressed client never appears at
    all. `lease_expires_at_ms` is carried so the UI can say which of these are
    still live rather than implying a connection that may be long gone.
    """

    mac_address: str
    """The client's hardware address, lowercased."""

    ip_address: str
    """The IPv4 address leased to it, e.g. "10.42.0.37"."""

    hostname: str | None
    """The name the client advertised, or None when it sent none (dnsmasq writes "*")."""

    lease_expires_at_ms: int
    """Unix milliseconds at which this lease expires."""


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
