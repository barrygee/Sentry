"""`GET /api/health` (architecture §7.1). Always auth-exempt."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.backend.dependencies import get_health_service
from app.backend.schemas.health import HealthResponse
from app.backend.services.health import HealthService

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health snapshot",
)
async def get_health(
    response: Response,
    health_service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Return the current health snapshot.

    200 unless the database is unreachable, in which case 503 with the same
    body shape — a flapping healthcheck on one degraded dongle must never
    restart the container and take the healthy dongles down with it
    (architecture §7.1). No auth dependency is declared on this router: the
    Docker healthcheck must reach it regardless of `SENTRY_AUTH_TOKEN`.
    """
    snapshot = await health_service.get_health()
    if snapshot.status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot
