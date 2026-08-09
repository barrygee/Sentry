"""Authentication for the management API (ADR-0010).

One credential — the console password — proved by a signed session cookie the
browser sends automatically. This replaced `SENTRY_AUTH_TOKEN`, and two of the
differences are visible right here:

* there is no SSE special case. `EventSource` cannot set an `Authorization`
  header, so the token had to be accepted from `?access_token=` on
  `GET /api/events`, putting a credential in browser history and — but for a
  bespoke log format — the access log. Cookies are sent on same-origin requests
  whatever the API, so that path is gone rather than mitigated;
* **an unprotected console is a supported state, not a misconfiguration.** With
  no password set, every dependency here passes. A fresh install is usable
  immediately and the UI asks the operator to set one; nothing here decides that
  for them.

Routes that must stay reachable regardless — `GET /api/health` for the Docker
healthcheck, and `GET /api/v1/sdrs` for Sentinel — simply do not depend on this.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.backend.dependencies import get_console_auth_service
from app.backend.services.console_auth import SESSION_COOKIE_NAME, ConsoleAuthService

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "unauthenticated", "message": "Sign in to continue."},
)
"""One response for every failure.

Deliberately identical whether no cookie was sent, the signature was forged, the
session expired, or the password has since changed. Distinguishing them would
tell an attacker which half of a guess was right, and tells a legitimate client
nothing it can act on beyond "sign in again".
"""


async def require_console_session(
    request: Request,
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
) -> None:
    """Require a valid session on every management route.

    A no-op while no password is set, which is the documented open default. The
    check is made per request rather than cached: setting a password must lock
    the API immediately, not at the next restart.
    """
    if not await console_auth.is_password_set():
        return
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not await console_auth.session_is_valid(cookie):
        raise _UNAUTHENTICATED
