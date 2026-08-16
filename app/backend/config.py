"""Application configuration.

The only place `os.environ` is read (architecture §4.4). Every documented
environment variable (architecture §3.4) is declared here with its documented
default; nothing else in the codebase should call `os.getenv` directly.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.backend.schemas.hotspot import validate_gateway_cidr

# The vendored relay ships inside this package, so its location is derived from
# the package itself rather than hard-coded. An absolute default would be wrong
# in one environment or the other: the container lays the backend out under
# /app/app/backend/, while a non-Docker run has it wherever the checkout lives.
_VENDORED_RELAY_PATH = Path(__file__).resolve().parent / "relay" / "rtl_tcp_relay.py"


class Settings(BaseSettings):
    """Sentry's runtime configuration, sourced from the environment / `.env`."""

    model_config = SettingsConfigDict(
        env_prefix="SENTRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    http_host: str = Field(default="0.0.0.0", description="API/SPA bind address")
    http_port: int = Field(default=8000, ge=1, le=65535, description="API/SPA port")
    advertised_host: str | None = Field(
        default=None,
        description=(
            "Host published in GET /api/v1/sdrs; when unset, derived from the request Host header"
        ),
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:////data/sentry.db",
        description="Async SQLAlchemy database URL",
    )
    max_devices: int = Field(
        default=8, ge=1, le=64, description="Bounds the internal port range and USB bandwidth"
    )
    internal_port_base: int = Field(
        default=14000,
        ge=1024,
        le=65535,
        description="Loopback rtl_tcp range [base, base + max_devices)",
    )
    reserved_ports: str = Field(
        default="", description="Extra operator deny-list, comma-separated port numbers"
    )
    sysfs_root: str = Field(
        default="/sys", description="Overridden by tests to a fixture sysfs tree"
    )
    reconcile_interval_s: float = Field(
        default=2.0, gt=0, description="Sysfs sweep period (hotplug safety net)"
    )
    rtl_tcp_path: str = Field(default="rtl_tcp", description="rtl_tcp binary path")
    rtl_eeprom_path: str = Field(default="rtl_eeprom", description="rtl_eeprom binary path")
    relay_path: str = Field(
        default=str(_VENDORED_RELAY_PATH),
        description="Path to the vendored, unmodified relay",
    )
    log_level: str = Field(default="INFO", description="Python logging level name")
    cors_origins: str = Field(
        default="",
        description=(
            "Comma-separated allow-list for a separately-hosted dev frontend; empty "
            "closes CORS entirely (the SPA is same-origin in production)"
        ),
    )

    hotspot_control_enabled: bool = Field(
        default=False,
        description=(
            "Allows the API to reconfigure this host's WiFi (ADR-0007). OFF by default: "
            "it is the one setting that gives a LAN-facing API control of host networking"
        ),
    )
    hotspot_require_auth_token: bool = Field(
        default=True,
        description=(
            "Refuse every hotspot change while auth_token is unset — an access point puts "
            "strangers one join away from this API"
        ),
    )
    hotspot_connection_name: str = Field(
        default="sentry-hotspot",
        pattern=r"^[A-Za-z0-9_-]{1,32}$",
        description="The single NetworkManager profile Sentry owns; never any other",
    )
    hotspot_interface: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]{1,15}$",
        description="Wireless interface for the hotspot; unset chooses an unused one automatically",
    )
    hotspot_gateway_cidr: str = Field(
        default="10.42.0.1/24",
        description="The Pi's address on the hotspot network — what a client points Sentinel at",
    )
    hotspot_confirm_timeout_s: float = Field(
        default=120.0,
        ge=15,
        le=900,
        description="How long a hotspot activation has to be confirmed before it rolls back",
    )
    # Wired sharing (ADR-0014). There is deliberately no `wired_control_enabled`
    # here: `hotspot_control_enabled` above is the host-network control switch,
    # and sharing an Ethernet port is that same capability. A second variable
    # would ask an operator to grant one permission twice.
    wired_connection_name: str = Field(
        default="sentry-wired",
        pattern=r"^[A-Za-z0-9_-]{1,32}$",
        description="The single NetworkManager wired profile Sentry owns; never any other",
    )
    wired_interface: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]{1,15}$",
        description=(
            "Ethernet port to share; unset chooses an unused one automatically. On a "
            "single-port Pi there is no unused one, so this (or the request) must name it"
        ),
    )
    wired_gateway_cidr: str = Field(
        default="10.10.10.1/24",
        description=(
            "The Pi's address on the shared Ethernet network — what a cabled machine "
            "points Sentinel at. A different subnet from the hotspot's on purpose"
        ),
    )
    wired_confirm_timeout_s: float = Field(
        default=120.0,
        ge=15,
        le=900,
        description="How long a wired-sharing activation has to be confirmed before it rolls back",
    )
    nmcli_path: str = Field(default="nmcli", description="nmcli binary path")
    nmcli_timeout_s: float = Field(
        default=20.0, gt=0, le=120, description="Per-command timeout for nmcli invocations"
    )
    nm_state_root: str = Field(
        default="/var/lib/NetworkManager",
        description="Where NetworkManager keeps its dnsmasq lease files; overridden by tests",
    )

    @field_validator("hotspot_gateway_cidr")
    @classmethod
    def _validate_hotspot_gateway_cidr(cls, gateway_cidr: str) -> str:
        """Reject a gateway address that would strand every client that joins.

        Validated here rather than only at the request edge because this value
        is the fallback used whenever a request does not name one — a typo in
        `.env` would otherwise surface as a hotspot that comes up and hands out
        unusable leases, which is a far worse failure than refusing at startup.
        """
        return validate_gateway_cidr(gateway_cidr)

    @field_validator("wired_gateway_cidr")
    @classmethod
    def _validate_wired_gateway_cidr(cls, gateway_cidr: str) -> str:
        """Reject a shared-port address that would strand every cabled machine.

        Same rule and same reasoning as the hotspot's: this value is the
        fallback used whenever a request does not name one, so a typo in `.env`
        would surface as a share that comes up and hands out unusable leases
        rather than as a refusal at startup.
        """
        return validate_gateway_cidr(gateway_cidr)

    @model_validator(mode="after")
    def _check_shared_ranges_do_not_overlap(self) -> Settings:
        """Refuse a wired range that overlaps the hotspot's.

        Both features raise a `shared` connection with its own DHCP server, and
        both can run at once on this Pi. Overlapping ranges would give the host
        the same address on two interfaces, and the kernel would route one of
        them into the other — a failure that presents as "the hotspot randomly
        stopped working" long after the config change that caused it, which is
        exactly the kind of thing worth refusing at startup instead.
        """
        hotspot_network = ipaddress.IPv4Interface(self.hotspot_gateway_cidr).network
        wired_network = ipaddress.IPv4Interface(self.wired_gateway_cidr).network
        if hotspot_network.overlaps(wired_network):
            raise ValueError(
                f"SENTRY_WIRED_GATEWAY_CIDR ({self.wired_gateway_cidr}) overlaps "
                f"SENTRY_HOTSPOT_GATEWAY_CIDR ({self.hotspot_gateway_cidr}); the hotspot "
                "and the wired share each run their own DHCP server and need "
                "separate ranges"
            )
        return self

    def wired_gateway_address(self) -> str:
        """Return just the shared-port IP (`"10.10.10.1"`) without its prefix length.

        This is the address a human types into Sentinel by hand after plugging
        a cable in, so it is surfaced on its own rather than making every caller
        re-split the CIDR.
        """
        return str(ipaddress.IPv4Interface(self.wired_gateway_cidr).ip)

    def hotspot_gateway_address(self) -> str:
        """Return just the gateway IP (`"10.42.0.1"`) without its prefix length.

        This is the address a human types into Sentinel by hand, so it is
        surfaced on its own rather than making every caller re-split the CIDR.
        """
        return str(ipaddress.IPv4Interface(self.hotspot_gateway_cidr).ip)

    def reserved_port_numbers(self) -> frozenset[int]:
        """Parse `reserved_ports` into a set of integers, ignoring blank entries.

        Raises `ValueError` with the offending entry named, rather than
        letting a bare `int()` typo crash startup with an unattributed
        `ValueError: invalid literal for int() with base 10: '...'` that
        gives the operator no clue which of possibly several comma-separated
        entries in `SENTRY_RESERVED_PORTS` was malformed.
        """
        port_numbers: set[int] = set()
        for raw_entry in self.reserved_ports.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            try:
                port_numbers.add(int(entry))
            except ValueError as error:
                raise ValueError(
                    f"SENTRY_RESERVED_PORTS entry {entry!r} is not a valid port number "
                    f"(full value: {self.reserved_ports!r})"
                ) from error
        return frozenset(port_numbers)

    def cors_origin_list(self) -> list[str]:
        """Parse `cors_origins` into a list of origins, ignoring blank entries."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings` instance, constructed once and cached.

    `lru_cache` gives dependency-injected call sites (`Depends(get_settings)`)
    a stable singleton without a module-level global.
    """
    return Settings()
