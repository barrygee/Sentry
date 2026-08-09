"""`/api/auth` — sign in, sign out, and set or change the console password (ADR-0010).

Deliberately **not** behind `require_console_session`. Every route here is
reachable without a session, because each is either how you get one or how you
find out whether you need one. The protection is inside the handlers instead:
changing an existing password requires the current one, and setting the first is
only possible while none exists.

That last rule is the one worth stating plainly. On an open console, anyone who
can reach it can set the first password — and thereby lock everyone else out.
That is the same exposure the console already has (they could equally rename
every device and disable every radio), and it is why the UI asks for a password
on first run and keeps asking. It is not a hole this router opens; it is the
open default, which ADR-0010 chose knowingly.
"""

from __future__ import annotations

from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.backend.dependencies import get_console_auth_service
from app.backend.schemas.errors import error_detail
from app.backend.services.console_auth import (
    MINIMUM_PASSWORD_LENGTH,
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME_S,
    ConsoleAuthService,
    PasswordTooShortError,
)

router = APIRouter(tags=["auth"])


class AuthStateResponse(BaseModel):
    """What a client needs to decide between "sign in", "set a password", and "carry on"."""

    model_config = ConfigDict(frozen=True)

    password_set: bool = Field(description="Whether this console has a password at all")
    authenticated: bool = Field(
        description="Whether this request carries a valid session, or none is required"
    )
    updated_at: int = Field(description="Unix ms the password last changed; 0 if never")
    minimum_password_length: int = Field(
        default=MINIMUM_PASSWORD_LENGTH, description="Shortest password the API will accept"
    )


class LoginRequest(BaseModel):
    """`POST /api/auth/login` body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    password: SecretStr
    """`SecretStr` so a validation error or stray log line cannot echo it back."""


class SetPasswordRequest(BaseModel):
    """`POST /api/auth/password` body — sets the first password, or changes an existing one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    new_password: SecretStr
    current_password: SecretStr | None = Field(
        default=None, description="Required when a password is already set; ignored when not"
    )


def _set_session_cookie(response: Response, value: str) -> None:
    """Attach the session cookie.

    `httponly` keeps it away from any script on the page, so an XSS bug cannot
    read the session out. `samesite="strict"` is what removes the CSRF exposure
    a cookie would otherwise add: the browser will not attach this cookie to a
    request another site originated. Nothing here has a cross-site flow to
    break, so strict costs nothing.

    `secure` is deliberately **not** set. This console is served over plain HTTP
    on a LAN — marking the cookie secure would mean it was never sent at all,
    which is not a security improvement but a total failure to log in.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value,
        max_age=SESSION_LIFETIME_S,
        httponly=True,
        samesite="strict",
        path="/",
    )


@router.get("/auth/state", response_model=AuthStateResponse, summary="Authentication state")
async def get_auth_state(
    request: Request,
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
) -> AuthStateResponse:
    """Report whether a password is set and whether this request is authenticated.

    The first call any client makes. An open console answers
    `password_set=false, authenticated=true` — nothing to sign in to.
    """
    state = await console_auth.state()
    if not state.password_set:
        return AuthStateResponse(password_set=False, authenticated=True, updated_at=0)

    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    return AuthStateResponse(
        password_set=True,
        authenticated=await console_auth.session_is_valid(cookie),
        updated_at=state.updated_at,
    )


@router.post("/auth/login", status_code=status.HTTP_204_NO_CONTENT, summary="Sign in")
async def login(
    body: LoginRequest,
    response: Response,
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
) -> Response:
    """Exchange the console password for a session cookie."""
    if not await console_auth.verify_password(body.password.get_secret_value()):
        # Same answer whether no password is set or the password was wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("invalid_password", "That password is not correct."),
        )
    _set_session_cookie(response, await console_auth.issue_session())
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(response: Response) -> Response:
    """Discard this browser's session.

    Clears the cookie and nothing else. Sessions are stateless signatures, so
    there is no server-side record to delete — a copy of the cookie taken from
    elsewhere stays valid until it expires or the password changes. Signing every
    session out is what changing the password is for, and the UI says so.
    """
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/auth/password", status_code=status.HTTP_204_NO_CONTENT, summary="Set or change the password"
)
async def set_password(
    body: SetPasswordRequest,
    response: Response,
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
) -> Response:
    """Set the first password, or change an existing one.

    Signs this browser straight back in. Changing the password invalidates every
    session including the caller's, so without a fresh cookie the operator would
    be bounced to a login screen by their own successful password change.
    """
    current = body.current_password.get_secret_value() if body.current_password else None
    try:
        await console_auth.set_password(
            body.new_password.get_secret_value(), current_password=current
        )
    except PasswordTooShortError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail("password_too_short", str(error)),
        ) from error
    except VerificationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                "current_password_incorrect", "The current password is not correct."
            ),
        ) from error

    _set_session_cookie(response, await console_auth.issue_session())
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
