"""Assemble the `GET /api/health` snapshot (architecture §4.3, §7.1).

**Clock note.** The composition root's frozen 4-argument constructor
(`device_registry`, `hotplug`, `started_at_ms`, `version` — no `Clock`) does
not thread a `Clock` through to this service, so `uptime_s` is computed from
`time.time()` directly rather than an injected `Clock.now_ms()`. This is the
one deliberate exception to "every service takes time through `Clock`" in
this module: it is a single read-only wall-clock reading with no sleep,
backoff, or debounce logic riding on it, so it costs nothing in testability
that a future `Clock` parameter wouldn't already give for free. Flagged in
the Phase 2A handoff.
"""

from __future__ import annotations

import time

from app.backend.schemas.device import DeviceStatus
from app.backend.schemas.health import DeviceCounts, HealthResponse, HealthStatus, HotplugHealth
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.hotplug import HotplugService


def _count_devices(statuses: tuple[DeviceStatus, ...]) -> DeviceCounts:
    """Tally the per-state counts `GET /api/health`'s `devices` field reports."""
    return DeviceCounts(
        present=sum(1 for status in statuses if status.present),
        configured=sum(1 for status in statuses if status.record_id is not None),
        streaming=sum(1 for status in statuses if status.state == "streaming"),
        degraded=sum(1 for status in statuses if status.state == "degraded"),
        error=sum(1 for status in statuses if status.state == "error"),
        needs_identification=sum(1 for status in statuses if status.needs_identification),
    )


_HEALTH_CACHE_TTL_S = 4.0
"""Just under the SSE heartbeat cadence (`HEALTH_HEARTBEAT_INTERVAL_S` in
`routers/events.py`, 5s) so every open SSE connection's own heartbeat still
sees a snapshot at least once per cycle, while a burst of many concurrent
connections (each independently calling `get_health()` on its own 5s timer,
plus `GET /api/health` itself) shares one DB ping instead of issuing one per
connection every 5 seconds — the amplification path a fleet with many open
tabs would otherwise hit."""


class HealthService:
    """Combines registry state, hotplug health and a DB ping into one health snapshot."""

    def __init__(
        self,
        device_registry: DeviceRegistry,
        hotplug: HotplugService,
        started_at_ms: int,
        version: str,
    ) -> None:
        self._device_registry = device_registry
        self._hotplug = hotplug
        self._started_at_ms = started_at_ms
        self._version = version
        self._cached_response: HealthResponse | None = None
        self._cached_at_monotonic: float | None = None

    async def get_health(self) -> HealthResponse:
        """Build the current health snapshot, reusing one within `_HEALTH_CACHE_TTL_S`.

        `status` is `"unhealthy"` (mapped by the router to HTTP 503) only
        when the database ping fails — a flapping healthcheck on one
        degraded dongle must never restart the container and take the
        healthy dongles down with it (architecture §7.1).
        """
        now_monotonic = time.monotonic()
        if (
            self._cached_response is not None
            and self._cached_at_monotonic is not None
            and now_monotonic - self._cached_at_monotonic < _HEALTH_CACHE_TTL_S
        ):
            return self._cached_response

        database_reachable = await self._device_registry.ping_database()
        device_counts = _count_devices(self._device_registry.list_statuses())
        hotplug_healthy = self._hotplug.is_primary_source_healthy()

        status: HealthStatus
        if not database_reachable:
            status = "unhealthy"
        elif hotplug_healthy and device_counts.degraded == 0 and device_counts.error == 0:
            status = "ok"
        else:
            status = "degraded"

        response = HealthResponse(
            status=status,
            version=self._version,
            started_at=self._started_at_ms,
            uptime_s=max((time.time() * 1000 - self._started_at_ms) / 1000, 0.0),
            database="ok" if database_reachable else "error",
            hotplug=HotplugHealth(
                source="udev" if hotplug_healthy else "reconcile",
                healthy=hotplug_healthy,
                last_event_at=self._hotplug.last_event_at_ms(),
            ),
            devices=device_counts,
        )
        self._cached_response = response
        self._cached_at_monotonic = now_monotonic
        return response
