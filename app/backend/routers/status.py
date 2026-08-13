"""`GET /api/status` (architecture §7.2). Requires bearer auth when configured."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.backend.config import Settings
from app.backend.dependencies import (
    get_clock,
    get_device_registry,
    get_sentry_location_service,
    get_settings_dependency,
)
from app.backend.interfaces.clock import Clock
from app.backend.routers.host_resolution import resolve_public_host, with_resolved_hosts
from app.backend.schemas.device import StatusResponse
from app.backend.security import require_console_session
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.sentry_location import SentryLocationService

router = APIRouter(tags=["status"], dependencies=[Depends(require_console_session)])


@router.get(
    "/status",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Realtime per-SDR status",
)
async def get_status(
    request: Request,
    device_registry: DeviceRegistry = Depends(get_device_registry),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings_dependency),
    location_service: SentryLocationService = Depends(get_sentry_location_service),
) -> StatusResponse:
    """Return the realtime per-SDR view — identical payload to the SSE `snapshot` event.

    The registry cannot know the publishable host, so it emits `output.host=""`;
    it is overlaid here (architecture §7.7) so consumers of this endpoint get the
    same reachable address `/api/v1/sdrs` reports.
    """
    host = resolve_public_host(request, settings)
    return StatusResponse(
        generated_at=clock.now_ms(),
        # The operator-set position, so a Sentinel polling this endpoint can plot
        # the Pi without a second call — see `schemas/location.py`.
        location=await location_service.get_location(),
        sdrs=with_resolved_hosts(device_registry.list_statuses(), host),
    )
