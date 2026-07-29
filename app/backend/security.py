"""Bearer-token authentication (architecture §7.9).

A single FastAPI dependency, a no-op when `SENTRY_AUTH_TOKEN` is unset (the
default for a single-purpose device on a trusted LAN). `GET /api/health` is
always exempt so the Docker healthcheck can reach it regardless of auth mode.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status

from app.backend.config import Settings, get_settings


async def require_bearer_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Enforce `Authorization: Bearer <token>` on every `/api/**` route except health.

    When `SENTRY_AUTH_TOKEN` is unset, this dependency is a no-op — auth is
    off entirely. When set, the token is compared with
    `secrets.compare_digest` (constant-time) and a missing/wrong token raises
    `401` with `WWW-Authenticate: Bearer` and no further detail, so a failed
    auth attempt never leaks whether the path or the token was the problem.

    `EventSource` cannot set headers, so `GET /api/events` additionally
    accepts the token via `?access_token=`; that acceptance is implemented in
    the events router, which calls this same comparison — never a relaxed
    one — before falling through to the header check.
    """
    if settings.auth_token is None:
        return
    header_value = request.headers.get("authorization", "")
    expected_header = f"Bearer {settings.auth_token}"
    if not secrets.compare_digest(header_value, expected_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Authentication required."},
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_sse_bearer_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Authenticate `GET /api/events`, which additionally accepts `?access_token=`.

    `EventSource` cannot set an `Authorization` header, so this dependency
    checks the header first and falls back to the query parameter — both
    compared with the same constant-time function as every other route
    (architecture §7.9). Query strings are stripped from Sentry's uvicorn
    access-log format so this trade-off never leaks the token into logs.
    """
    if settings.auth_token is None:
        return
    header_value = request.headers.get("authorization", "")
    if secrets.compare_digest(header_value, f"Bearer {settings.auth_token}"):
        return
    if token_matches(settings, request.query_params.get("access_token")):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Authentication required."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def token_matches(settings: Settings, candidate: str | None) -> bool:
    """Constant-time comparison of `candidate` against the configured token.

    Shared by the header check above and the SSE `?access_token=` fallback
    (architecture §7.9) so there is exactly one comparison implementation.
    Returns True when auth is off (`settings.auth_token is None`) — callers
    that need to distinguish "auth off" from "token matched" check
    `settings.auth_token is None` themselves first.
    """
    if settings.auth_token is None:
        return True
    if candidate is None:
        return False
    return secrets.compare_digest(candidate, settings.auth_token)
