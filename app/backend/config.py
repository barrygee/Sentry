"""Application configuration.

The only place `os.environ` is read (architecture §4.4). Every documented
environment variable (architecture §3.4) is declared here with its documented
default; nothing else in the codebase should call `os.getenv` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    auth_token: str | None = Field(
        default=None,
        description="Bearer token required on /api/** when set; unset disables auth",
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

    def reserved_port_numbers(self) -> frozenset[int]:
        """Parse `reserved_ports` into a set of integers, ignoring blank entries."""
        return frozenset(
            int(value.strip()) for value in self.reserved_ports.split(",") if value.strip()
        )

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
