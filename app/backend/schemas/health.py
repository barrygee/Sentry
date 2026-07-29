"""`GET /api/health` response shape (architecture §7.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HealthStatus = Literal["ok", "degraded", "unhealthy"]
"""`unhealthy` is returned with HTTP 503 (database unreachable); the other two with 200."""

HotplugSourceName = Literal["udev", "reconcile"]


class HotplugHealth(BaseModel):
    """Whether the primary hotplug mechanism (udev) or only the reconcile fallback is active."""

    model_config = ConfigDict(frozen=True)

    source: HotplugSourceName
    healthy: bool
    last_event_at: int | None = None


class DeviceCounts(BaseModel):
    """Per-state device tallies surfaced in the health snapshot."""

    model_config = ConfigDict(frozen=True)

    present: int = Field(ge=0)
    configured: int = Field(ge=0)
    streaming: int = Field(ge=0)
    degraded: int = Field(ge=0)
    error: int = Field(ge=0)
    needs_identification: int = Field(ge=0)


class HealthResponse(BaseModel):
    """`GET /api/health` body. Auth-exempt; 503 only when the database is unreachable."""

    model_config = ConfigDict(frozen=True)

    status: HealthStatus
    version: str
    started_at: int = Field(description="Unix ms the process started")
    uptime_s: float = Field(ge=0)
    database: Literal["ok", "error"]
    hotplug: HotplugHealth
    devices: DeviceCounts
