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

`PUT` and `POST` are the same operation here, sharing one handler. A Sentry has
exactly one position, so there is no collection for `POST` to append to and no
"create versus replace" distinction for the two verbs to split between them —
see `post_location`.
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


async def _store_location(
    request_body: SentryLocationUpdate,
    location_service: SentryLocationService,
) -> SentryLocation:
    """Shared body for `PUT` and `POST`.

    One function rather than two, so the pair cannot drift into disagreeing
    about what a write does — which is the failure a same-behaviour alias
    invites, and the only real cost of offering one.

    Bounds and the both-or-neither rule are enforced by `SentryLocationUpdate`,
    so anything reaching here is already a position Sentinel can plot (or an
    explicit erasure).
    """
    return await location_service.set_location(request_body.latitude, request_body.longitude)


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
    """Store the given coordinates, or clear the position when both are null."""
    return await _store_location(request_body, location_service)


@router.post(
    "",
    response_model=SentryLocation,
    status_code=status.HTTP_200_OK,
    summary="Set or clear this Sentry's fixed position (alias for PUT)",
)
async def post_location(
    request_body: SentryLocationUpdate,
    location_service: SentryLocationService = Depends(get_sentry_location_service),
) -> SentryLocation:
    """Identical to `PUT` — same body, same rules, same response.

    Offered because a Sentry has exactly one position, so "create" and
    "replace" are the same act: there is no collection to append to and no
    second location a `POST` could mean. Clients that reach for `POST` by
    habit (or whose HTTP layer makes `PUT` awkward) get the obvious verb
    instead of a 405 telling them to use another one.

    Deliberately **not** create-only. A `POST` that 409'd once a position
    existed would make the natural verb the one that stops working the moment
    it has been used, and an operator correcting a typo would be told the
    Sentry already has a location — which they knew, and are trying to change.

    Idempotent, as `PUT` is: sending the same pair twice leaves the same
    position, so a retried request after a dropped response is safe.
    """
    return await _store_location(request_body, location_service)
