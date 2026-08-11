"""`/api/hotspot*` request/response shapes (ADR-0007).

Every constraint here is an anchored allow-list rather than a deny-list, the
same discipline `schemas/serial.py`'s `SERIAL_PATTERN` follows: the values in
this module become elements of a `nmcli` argv, and the only safe question to
ask of them is "is this one of the things I expect", never "does this look
dangerous".

**The passphrase is write-only.** It is typed `SecretStr` so it cannot leak
through a stray `repr()`, it is absent from every response model in this file,
and there is no endpoint anywhere that returns it. Responses carry only
`passphrase_set: bool`.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

HotspotSecurity = Literal["wpa2", "wpa3"]
HotspotBand = Literal["bg", "a"]

SSID_MAX_BYTES = 32
"""802.11 caps the SSID element at 32 octets. Enforced in **bytes, not characters** —
eleven four-byte emoji is 44 bytes and must be rejected even though `len()` says 11."""

PASSPHRASE_PATTERN = re.compile(r"^[\x20-\x7e]{8,63}$")
"""WPA-Personal passphrases are defined over printable ASCII, 8-63 characters."""

RAW_PSK_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
"""The alternative form: a pre-computed 256-bit PSK as 64 hex characters."""

INTERFACE_PATTERN = r"^[A-Za-z0-9_.-]{1,15}$"
"""Linux caps an interface name at IFNAMSIZ-1 = 15 characters."""

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")

CHANNELS_2GHZ = frozenset(range(1, 15))
"""Channels 1-14. Which are actually usable depends on the regulatory domain."""

CHANNELS_5GHZ = frozenset(
    {
        36,
        40,
        44,
        48,
        52,
        56,
        60,
        64,
        100,
        104,
        108,
        112,
        116,
        120,
        124,
        128,
        132,
        136,
        140,
        144,
        149,
        153,
        157,
        161,
        165,
    }
)
"""The standard 5 GHz set. Again, regulatory domain decides what is usable — a
legal-but-unavailable channel surfaces as an activation failure, not a 400."""

GATEWAY_MIN_PREFIX = 16
GATEWAY_MAX_PREFIX = 30
"""Wide enough to be useful, narrow enough that a typo cannot claim half the
internet. /31 and /32 have no usable host range for clients at all."""


def validate_ssid(ssid: str) -> str:
    """Validate an SSID, returning it unchanged, or raise `ValueError` naming the constraint.

    Shared by the request schema and re-usable by anything else that needs the
    same rule, so the definition of a valid SSID exists exactly once.
    """
    if _CONTROL_CHARACTERS.search(ssid):
        raise ValueError("Network name must not contain control characters")
    if ssid != ssid.strip():
        # A leading or trailing space is legal 802.11 but invisible in every UI.
        # For a *hidden* network, which a client has to type by hand from memory,
        # an SSID that differs only by an unseeable space is an unjoinable one.
        raise ValueError("Network name must not start or end with a space")
    encoded_length = len(ssid.encode("utf-8"))
    if encoded_length < 1 or encoded_length > SSID_MAX_BYTES:
        raise ValueError(
            f"Network name must be 1 to {SSID_MAX_BYTES} bytes "
            f"(this one is {encoded_length}); note that accented and emoji "
            "characters cost more than one byte each"
        )
    return ssid


def validate_passphrase(passphrase: str) -> str:
    """Validate a WPA-Personal passphrase, returning it unchanged, or raise `ValueError`.

    Deliberately never trims. A leading or trailing space is a legal part of a
    passphrase, and silently removing one would produce a network nobody can
    join with the credentials they were given.
    """
    if PASSPHRASE_PATTERN.match(passphrase) or RAW_PSK_PATTERN.match(passphrase):
        return passphrase
    raise ValueError(
        "Password must be 8 to 63 characters using ordinary keyboard symbols, "
        "or a 64-character hexadecimal key"
    )


def validate_channel_for_band(channel: int, band: HotspotBand) -> int:
    """Validate a channel against its band, returning it unchanged, or raise `ValueError`."""
    if channel == 0:
        return channel
    allowed = CHANNELS_2GHZ if band == "bg" else CHANNELS_5GHZ
    if channel not in allowed:
        band_label = "2.4 GHz" if band == "bg" else "5 GHz"
        raise ValueError(
            f"Channel {channel} is not a {band_label} channel; use 0 to choose automatically"
        )
    return channel


def validate_gateway_cidr(gateway_cidr: str) -> str:
    """Validate the AP-side address, returning it unchanged, or raise `ValueError`.

    Private ranges only: this address is handed out by a DHCP server Sentry
    raises, and a public range there would blackhole real internet destinations
    for every joined client.
    """
    try:
        interface_address = ipaddress.IPv4Interface(gateway_cidr)
    except ValueError as error:
        raise ValueError(f"Address must look like 10.42.0.1/24 (got {gateway_cidr!r})") from error
    if not interface_address.ip.is_private:
        raise ValueError("Address must be in a private range (10.x, 172.16-31.x or 192.168.x)")
    prefix_length = interface_address.network.prefixlen
    if not GATEWAY_MIN_PREFIX <= prefix_length <= GATEWAY_MAX_PREFIX:
        raise ValueError(
            f"Network size must be between /{GATEWAY_MIN_PREFIX} and /{GATEWAY_MAX_PREFIX}"
        )
    if interface_address.ip == interface_address.network.network_address:
        raise ValueError("Address must not be the network address itself")
    if interface_address.ip == interface_address.network.broadcast_address:
        raise ValueError("Address must not be the broadcast address")
    return gateway_cidr


class HotspotConfigRequest(BaseModel):
    """`PUT /api/hotspot` body — a full replace, not a merge.

    Deliberately not a PATCH. Merging a partial body would let a request that
    says nothing about `hidden` silently inherit a previous `false`, which is
    exactly the security-relevant field an operator most expects to be
    explicit. The passphrase is the single exception, and only because omitting
    it is the mechanism that keeps the secret write-only.
    """

    model_config = ConfigDict(extra="forbid")

    ssid: str = Field(description="The network name clients look for; 1-32 UTF-8 bytes")
    passphrase: SecretStr | None = Field(
        default=None,
        description="Omit to keep the currently stored password unchanged",
    )
    security: HotspotSecurity = Field(
        default="wpa2", description="wpa3 is experimental on Raspberry Pi radios"
    )
    hidden: bool = Field(
        default=True,
        description=(
            "Suppress SSID broadcast so clients must know the name in advance. "
            "Not a security control on its own"
        ),
    )
    enabled: bool = Field(
        default=False, description="Whether the hotspot should be running after this call"
    )
    interface: str | None = Field(
        default=None,
        pattern=INTERFACE_PATTERN,
        description="Wireless interface to use; omit to choose one automatically",
    )
    band: HotspotBand = Field(default="bg", description="bg is 2.4 GHz, a is 5 GHz")
    channel: int = Field(default=0, ge=0, le=196, description="0 chooses automatically")
    gateway_cidr: str | None = Field(
        default=None,
        description="The Pi's address on the hotspot network; omit to use the configured default",
    )
    confirm_uplink_loss: bool = Field(
        default=False,
        description=(
            "Acknowledges that the chosen interface currently carries a connection "
            "which raising the hotspot will drop"
        ),
    )

    @field_validator("ssid")
    @classmethod
    def _check_ssid(cls, ssid: str) -> str:
        return validate_ssid(ssid)

    @field_validator("passphrase")
    @classmethod
    def _check_passphrase(cls, passphrase: SecretStr | None) -> SecretStr | None:
        if passphrase is None:
            return None
        validate_passphrase(passphrase.get_secret_value())
        return passphrase

    @field_validator("gateway_cidr")
    @classmethod
    def _check_gateway_cidr(cls, gateway_cidr: str | None) -> str | None:
        if gateway_cidr is None:
            return None
        return validate_gateway_cidr(gateway_cidr)

    @model_validator(mode="after")
    def _check_channel_against_band(self) -> HotspotConfigRequest:
        validate_channel_for_band(self.channel, self.band)
        return self


class HotspotActivationRequest(BaseModel):
    """Body shared by `POST /api/hotspot/enable` and `/disable`.

    These exist as their own routes so the UI's on/off switch never resends the
    whole configuration — and therefore never has to be holding the passphrase
    just to flip a switch.
    """

    model_config = ConfigDict(extra="forbid")

    confirm_uplink_loss: bool = Field(
        default=False,
        description="Acknowledges that this call will drop a connection currently in use",
    )


HotspotWarning = Literal[
    "auth_token_missing",
    "advertised_host_overrides_gateway",
    "single_radio_uplink_loss",
    "nm_unavailable",
]
"""Non-fatal conditions worth showing the operator. Warnings never block a read."""


class HotspotErrorSummary(BaseModel):
    """The last control failure, kept so the UI can explain a hotspot that is not up."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    ts: int = Field(description="Unix ms")
    stderr_tail: str | None = Field(
        default=None,
        description=(
            "Tail of the failing command's output, scrubbed of the hotspot passphrase. "
            "The only thing that says why NetworkManager refused"
        ),
    )


class HotspotStateResponse(BaseModel):
    """`GET /api/hotspot` and every mutator's success body.

    Never 503s: a host that cannot do any of this answers 200 with
    `available: false`, matching how the app already degrades when `librtlsdr`
    is missing. A client can therefore always render *something*.
    """

    model_config = ConfigDict(frozen=True)

    available: bool = Field(description="Whether access-point control works on this host")
    control_enabled: bool = Field(description="Whether SENTRY_HOTSPOT_CONTROL_ENABLED is set")
    auth_token_configured: bool = Field(description="Whether SENTRY_AUTH_TOKEN is set")
    configured: bool = Field(description="Whether a hotspot profile exists")
    enabled: bool = Field(description="Whether the profile is set to come up on boot")
    active: bool = Field(description="Whether the hotspot is running right now")
    interface: str | None = None
    ssid: str | None = None
    hidden: bool = True
    security: HotspotSecurity = "wpa2"
    band: HotspotBand = "bg"
    channel: int = Field(default=0, ge=0)
    gateway_address: str | None = Field(
        default=None,
        description="The address a joined client should point Sentinel at, e.g. 10.42.0.1",
    )
    gateway_cidr: str | None = None
    passphrase_set: bool = Field(
        default=False, description="Whether a password is stored; never the password itself"
    )
    uplink_interface_is_hotspot_interface: bool = Field(
        default=False,
        description="True when raising the hotspot would drop this host's own connection",
    )
    pending_confirmation: bool = Field(
        default=False,
        description="A hotspot change is awaiting confirmation and will roll back without it",
    )
    confirm_deadline_ms: int | None = Field(
        default=None, description="Unix ms by which POST /api/hotspot/confirm must arrive"
    )
    last_error: HotspotErrorSummary | None = None
    warnings: tuple[HotspotWarning, ...] = ()
    generated_at: int = Field(description="Unix ms")


class WirelessInterfaceItem(BaseModel):
    """One selectable wireless interface in `GET /api/hotspot/interfaces`."""

    model_config = ConfigDict(frozen=True)

    name: str
    mac_address: str | None = None
    supports_ap: bool | None = Field(
        default=None, description="null when this NetworkManager version does not report it"
    )
    state: str
    station_ssid: str | None = Field(
        default=None, description="The network this interface is joined to as a client, if any"
    )
    ipv4_addresses: tuple[str, ...] = ()
    carries_default_route: bool = False
    in_use_by: str | None = Field(
        default=None, description="The connection currently active on this interface, if any"
    )


class WirelessInterfacesResponse(BaseModel):
    """`GET /api/hotspot/interfaces` body. Empty when nothing can be enumerated."""

    model_config = ConfigDict(frozen=True)

    interfaces: tuple[WirelessInterfaceItem, ...] = ()
    generated_at: int = Field(description="Unix ms")


class HotspotClientItem(BaseModel):
    """One DHCP lease issued by the hotspot."""

    model_config = ConfigDict(frozen=True)

    mac_address: str
    ip_address: str
    hostname: str | None = None
    lease_expires_at_ms: int = Field(description="Unix ms")
    expired: bool = Field(description="Whether the lease has already lapsed")


class HotspotClientsResponse(BaseModel):
    """`GET /api/hotspot/clients` body.

    `clients` is `null`, never `[]`, when no lease file could be read — "we
    cannot tell" and "nobody is connected" are different answers and the UI
    renders them differently.
    """

    model_config = ConfigDict(frozen=True)

    clients: tuple[HotspotClientItem, ...] | None = None
    source: Literal["dnsmasq-leases"] = "dnsmasq-leases"
    generated_at: int = Field(description="Unix ms")


class HotspotControlRequest(BaseModel):
    """Turn this Sentry's hotspot control on or off (ADR-0013)."""

    enabled: bool = Field(description="Whether the API may reconfigure this host's WiFi")


class HotspotControlResponse(BaseModel):
    """The state of the hotspot-control switch after a change."""

    control_enabled: bool = Field(description="Whether hotspot control is now in effect")
    forced_by_environment: bool = Field(
        description=(
            "Whether SENTRY_HOTSPOT_CONTROL_ENABLED pins control on, making the stored "
            "value moot until it is removed"
        )
    )
