"""The console password, and the sessions it issues (ADR-0010).

Replaces `SENTRY_AUTH_TOKEN`. The differences that matter:

* the credential is chosen by a person and stored hashed, so it can be changed
  from the UI rather than by editing `.env` and recreating the container;
* it is held in a cookie the browser sends automatically, which is what lets
  `GET /api/events` drop the `?access_token=` query parameter that put a
  credential into browser history and access logs;
* **there is no password by default.** A fresh install is open, exactly as it
  was before a token was set, and `password_hash IS NULL` is that state.

Sessions are stateless: a signed cookie, not a row. There is no session table to
grow, expire or garbage-collect, and a restart does not sign everybody out. The
cost is that an individual session cannot be revoked — only all of them at once,
by changing the password or resetting the secret — which is the right trade for
a console with a single credential and no notion of separate users.
"""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backend.models import ConsoleAuthModel

SESSION_COOKIE_NAME = "sentry_session"
"""Name of the session cookie. Same-origin only; never sent cross-site."""

SESSION_LIFETIME_S = 30 * 24 * 60 * 60
"""How long a session lasts: 30 days.

Long on purpose. This is a console on a home network, and the failure mode of a
short session — being signed out mid-task on a Pi you are stood next to — is far
more likely to be met with a weaker password than a shorter window ever was to
prevent anything. Changing the password ends every session immediately, which is
the control that actually matters.
"""

MINIMUM_PASSWORD_LENGTH = 8
"""Short enough not to drive people to a sticky note, long enough to be worth hashing.

Deliberately no composition rules — no "one capital, one symbol". They push
people towards `Password1!` and are not what makes a password hard to guess.
"""

_password_hasher = PasswordHasher()
"""argon2id with the library's defaults, which track current guidance."""


@dataclass(frozen=True)
class ConsoleAuthState:
    """What the API reports about authentication, for a client deciding what to render."""

    password_set: bool
    """Whether a password exists. `False` means the console is open to anyone."""

    updated_at: int
    """Unix ms the password last changed; 0 when none has ever been set."""


class PasswordTooShortError(ValueError):
    """Raised when a proposed password is below `MINIMUM_PASSWORD_LENGTH`."""


class ConsoleAuthService:
    """Reads and writes the single `console_auth` row, and signs session cookies."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _row(self, session: AsyncSession) -> ConsoleAuthModel:
        """Fetch the single row, which the migration guarantees exists."""
        result = await session.execute(select(ConsoleAuthModel).where(ConsoleAuthModel.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            # Only reachable if someone deleted the row by hand. Recreating it
            # open is the least surprising recovery: the console behaves like a
            # fresh install rather than locking everyone out of their own Pi.
            row = ConsoleAuthModel(
                id=1, password_hash=None, password_version=0, session_secret=_new_secret()
            )
            session.add(row)
            await session.flush()
        return row

    async def state(self) -> ConsoleAuthState:
        """Whether a password is set, and when it last changed."""
        async with self._session_factory() as session:
            row = await self._row(session)
            return ConsoleAuthState(
                password_set=row.password_hash is not None, updated_at=row.updated_at
            )

    async def is_password_set(self) -> bool:
        """Whether the console is protected at all."""
        return (await self.state()).password_set

    async def set_password(self, new_password: str, *, current_password: str | None) -> None:
        """Set or change the console password.

        `current_password` must match when one is already set. It is `None` only
        for the first password on an open console — where there is no secret to
        prove knowledge of, and requiring one would make the console
        unprotectable rather than secure.

        Raises `PasswordTooShortError`, or `VerificationError` when
        `current_password` is wrong.
        """
        if len(new_password) < MINIMUM_PASSWORD_LENGTH:
            raise PasswordTooShortError(
                f"Password must be at least {MINIMUM_PASSWORD_LENGTH} characters."
            )

        async with self._session_factory() as session:
            row = await self._row(session)

            if row.password_hash is not None:
                if current_password is None:
                    raise VerificationError("The current password is required.")
                _verify_hash(row.password_hash, current_password)

            row.password_hash = _password_hasher.hash(new_password)
            # Every existing session dies here. Someone changing their password
            # because they think it is known expects exactly that.
            row.password_version += 1
            row.updated_at = int(time.time() * 1000)
            await session.commit()

    async def verify_password(self, candidate: str) -> bool:
        """Whether `candidate` is the console password. `False` when none is set."""
        async with self._session_factory() as session:
            row = await self._row(session)
            if row.password_hash is None:
                return False
            try:
                _verify_hash(row.password_hash, candidate)
            except (VerificationError, InvalidHashError):
                return False

            # Rehash when argon2's parameters have moved on since this hash was
            # written — the one moment the plaintext is legitimately in hand.
            if _password_hasher.check_needs_rehash(row.password_hash):
                row.password_hash = _password_hasher.hash(candidate)
                await session.commit()
            return True

    async def issue_session(self) -> str:
        """Mint a signed session value for the cookie."""
        async with self._session_factory() as session:
            row = await self._row(session)
            issued_at = int(time.time())
            payload = f"{row.password_version}.{issued_at}"
            return f"{payload}.{_sign(row.session_secret, payload)}"

    async def session_is_valid(self, cookie_value: str | None) -> bool:
        """Whether a cookie authorises this request.

        Rejects anything malformed, expired, or signed against a different
        password version — the last being what makes a password change sign
        every existing session out.
        """
        if not cookie_value:
            return False

        parts = cookie_value.split(".")
        if len(parts) != 3:
            return False
        version_text, issued_text, signature = parts

        async with self._session_factory() as session:
            row = await self._row(session)

            expected = _sign(row.session_secret, f"{version_text}.{issued_text}")
            # Constant-time: a signature check that returns early leaks how much
            # of a forgery was right, one byte at a time.
            if not hmac.compare_digest(signature, expected):
                return False

            try:
                version = int(version_text)
                issued_at = int(issued_text)
            except ValueError:
                return False

            if version != row.password_version:
                return False
            return 0 <= time.time() - issued_at <= SESSION_LIFETIME_S

    async def clear_password(self) -> None:
        """Remove the password, returning the console to open. Ends every session.

        The recovery path for a forgotten password, driven from the Pi itself —
        which is the same authority that could read the database anyway, so it
        grants nothing that shell access did not already.
        """
        async with self._session_factory() as session:
            row = await self._row(session)
            row.password_hash = None
            row.password_version += 1
            row.session_secret = _new_secret()
            row.updated_at = int(time.time() * 1000)
            await session.commit()


def _new_secret() -> str:
    """A fresh session-signing secret."""
    return secrets.token_urlsafe(48)


def _sign(secret: str, payload: str) -> str:
    """HMAC-SHA256 of `payload` under `secret`, hex-encoded."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()


def _verify_hash(stored_hash: str, candidate: str) -> None:
    """Verify `candidate` against `stored_hash`, normalising argon2's exceptions."""
    try:
        _password_hasher.verify(stored_hash, candidate)
    except VerifyMismatchError as error:
        raise VerificationError("Incorrect password.") from error
