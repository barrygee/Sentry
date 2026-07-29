"""`GET /api/status` (architecture §7.2). Requires bearer auth when configured."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.backend.dependencies import get_clock, get_device_registry
from app.backend.interfaces.clock import Clock
from app.backend.schemas.device import StatusResponse
from app.backend.security import require_bearer_token
from app.backend.services.device_registry import DeviceRegistry

router = APIRouter(tags=["status"], dependencies=[Depends(require_bearer_token)])


@router.get(
    "/status",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Realtime per-SDR status",
)
async def get_status(
    device_registry: DeviceRegistry = Depends(get_device_registry),
    clock: Clock = Depends(get_clock),
) -> StatusResponse:
    """Return the realtime per-SDR view — identical payload to the SSE `snapshot` event."""
    return StatusResponse(generated_at=clock.now_ms(), sdrs=device_registry.list_statuses())
