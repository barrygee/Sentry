"""`/api/location` — read and set this Sentry's fixed geographic position.

The position exists so a Sentinel can plot this Pi on a map. Sentinel never
writes it: it arrives with the device list Sentinel already fetches
(`GET /api/status` and `GET /api/v1/sdrs`), and this router is the operator's
side of that — the console's Sentry Location panel is its only caller.

**Reading is gated on the console session, writing likewise.** The read is
gated even though the same coordinates are published unauthenticated on
`/api/v1/sdrs`, which looks redundant but is not: this endpoint reports the
position of a Sentry whose export may be empty, and consistency with every
other `/api/*` console route is worth more than saving a session check on a
route the console alone calls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.backend.dependencies import get_sentry_location_service
from app.backend.schemas.location import SentryLocation, SentryLocationUpdate
from app.backend.security import require_console_session
from app.backend.services.sentry_location import SentryLocationService

router = APIRouter(
    prefix="/location", tags=["location"], dependencies=[Depends(require_console_session)]
)


@router.get(
    "",
    response_model=SentryLocation,
    status_code=status.HTTP_200_OK,
    summary="This Sentry's fixed latitude / longitude",
)
async def get_location(
    location_service: SentryLocationService = Depends(get_sentry_location_service),
) -> SentryLocation:
    """Return the stored position, with both coordinates null when none is set."""
    return await location_service.get_location()


@router.put(
    "",
    response_model=SentryLocation,
    status_code=status.HTTP_200_OK,
    summary="Set or clear this Sentry's fixed position",
)
async def set_location(
    request_body: SentryLocationUpdate,
    location_service: SentryLocationService = Depends(get_sentry_location_service),
) -> SentryLocation:
    """Store the given coordinates, or clear the position when both are null.

    Bounds and the both-or-neither rule are enforced by `SentryLocationUpdate`,
    so anything reaching here is already a position Sentinel can plot (or an
    explicit erasure).
    """
    return await location_service.set_location(request_body.latitude, request_body.longitude)
