"""Tests for the console password and the sessions it issues (ADR-0010).

The security-relevant properties are asserted directly rather than inferred from
the routes, because each is a thing that would fail silently:

* a forged or expired cookie must not authenticate;
* changing the password must end every existing session, not just future ones;
* an open console (no password) must stay open rather than deny everything.

Run with:  uv run pytest tests/auth
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from argon2.exceptions import VerificationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.backend.models import Base, ConsoleAuthModel
from app.backend.services.console_auth import (
    MINIMUM_PASSWORD_LENGTH,
    SESSION_LIFETIME_S,
    ConsoleAuthService,
    PasswordTooShortError,
)

PASSWORD = "a good long password"
"""Comfortably over the minimum, and not the kind of thing a rule would demand."""


@pytest_asyncio.fixture
async def service(tmp_path: Path) -> AsyncIterator[ConsoleAuthService]:
    """A service over a throwaway SQLite file with the single row seeded."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ConsoleAuthModel(
                id=1,
                password_hash=None,
                password_version=0,
                session_secret="seed-secret",
                updated_at=0,
            )
        )
        await session.commit()

    yield ConsoleAuthService(factory)
    await engine.dispose()


class TestOpenConsole:
    """A fresh install has no password, and that is a supported state."""

    @pytest.mark.asyncio
    async def test_reports_no_password(self, service: ConsoleAuthService) -> None:
        assert (await service.state()).password_set is False

    @pytest.mark.asyncio
    async def test_verifying_any_password_fails(self, service: ConsoleAuthService) -> None:
        # Nothing to match. The route turns this into "that password is not
        # correct" rather than revealing that no password exists.
        assert await service.verify_password(PASSWORD) is False

    @pytest.mark.asyncio
    async def test_no_cookie_is_not_a_valid_session(self, service: ConsoleAuthService) -> None:
        # The *route* lets an open console through; the session check itself
        # never invents a session. Keeping that distinction here is what stops
        # "open" leaking into "any cookie will do" if the route changes.
        assert await service.session_is_valid(None) is False


class TestSettingAPassword:
    @pytest.mark.asyncio
    async def test_first_password_needs_no_current_password(
        self, service: ConsoleAuthService
    ) -> None:
        # There is no secret to prove knowledge of. Requiring one would make an
        # open console impossible to protect.
        await service.set_password(PASSWORD, current_password=None)

        assert (await service.state()).password_set is True

    @pytest.mark.asyncio
    async def test_rejects_a_password_below_the_minimum(self, service: ConsoleAuthService) -> None:
        with pytest.raises(PasswordTooShortError):
            await service.set_password("x" * (MINIMUM_PASSWORD_LENGTH - 1), current_password=None)

    @pytest.mark.asyncio
    async def test_accepts_a_password_exactly_at_the_minimum(
        self, service: ConsoleAuthService
    ) -> None:
        await service.set_password("x" * MINIMUM_PASSWORD_LENGTH, current_password=None)

        assert (await service.state()).password_set is True

    @pytest.mark.asyncio
    async def test_stores_a_hash_not_the_password(
        self, service: ConsoleAuthService, tmp_path: Path
    ) -> None:
        await service.set_password(PASSWORD, current_password=None)

        # The plaintext must not be recoverable from the database. This is the
        # whole reason for hashing, so it is asserted rather than assumed.
        database_bytes = (tmp_path / "auth.db").read_bytes()
        assert PASSWORD.encode() not in database_bytes

    @pytest.mark.asyncio
    async def test_records_when_it_changed(self, service: ConsoleAuthService) -> None:
        before = int(time.time() * 1000)

        await service.set_password(PASSWORD, current_password=None)

        assert (await service.state()).updated_at >= before


class TestChangingAPassword:
    @pytest.mark.asyncio
    async def test_requires_the_current_password(self, service: ConsoleAuthService) -> None:
        await service.set_password(PASSWORD, current_password=None)

        with pytest.raises(VerificationError):
            await service.set_password("a different password", current_password="wrong")

    @pytest.mark.asyncio
    async def test_refuses_when_the_current_password_is_omitted(
        self, service: ConsoleAuthService
    ) -> None:
        await service.set_password(PASSWORD, current_password=None)

        with pytest.raises(VerificationError):
            await service.set_password("a different password", current_password=None)

    @pytest.mark.asyncio
    async def test_a_failed_change_leaves_the_old_password_working(
        self, service: ConsoleAuthService
    ) -> None:
        await service.set_password(PASSWORD, current_password=None)

        with pytest.raises(VerificationError):
            await service.set_password("a different password", current_password="wrong")

        assert await service.verify_password(PASSWORD) is True

    @pytest.mark.asyncio
    async def test_succeeds_with_the_current_password(self, service: ConsoleAuthService) -> None:
        await service.set_password(PASSWORD, current_password=None)

        await service.set_password("a different password", current_password=PASSWORD)

        assert await service.verify_password("a different password") is True
        assert await service.verify_password(PASSWORD) is False


class TestSessions:
    @pytest.mark.asyncio
    async def test_an_issued_session_is_valid(self, service: ConsoleAuthService) -> None:
        await service.set_password(PASSWORD, current_password=None)

        assert await service.session_is_valid(await service.issue_session()) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "corrupt",
        [
            pytest.param(lambda cookie: "", id="empty"),
            pytest.param(lambda cookie: "nonsense", id="not-three-parts"),
            pytest.param(lambda cookie: f"{cookie}.extra", id="four-parts"),
            pytest.param(
                lambda cookie: ".".join(cookie.split(".")[:2] + ["0" * 64]), id="wrong-signature"
            ),
            pytest.param(
                lambda cookie: ".".join(["9", cookie.split(".")[1], cookie.split(".")[2]]),
                id="version-bumped",
            ),
            pytest.param(
                lambda cookie: ".".join(
                    [cookie.split(".")[0], str(int(cookie.split(".")[1]) + 5), cookie.split(".")[2]]
                ),
                id="issued-at-altered",
            ),
            pytest.param(lambda cookie: "a.b.c", id="non-numeric"),
        ],
    )
    async def test_a_tampered_cookie_is_rejected(
        self, service: ConsoleAuthService, corrupt
    ) -> None:
        await service.set_password(PASSWORD, current_password=None)
        cookie = await service.issue_session()

        assert await service.session_is_valid(corrupt(cookie)) is False

    @pytest.mark.asyncio
    async def test_an_expired_session_is_rejected(self, service: ConsoleAuthService) -> None:
        await service.set_password(PASSWORD, current_password=None)
        cookie = await service.issue_session()
        version, _issued, signature = cookie.split(".")

        # Forge the timestamp *and* keep the signature honest by re-signing —
        # otherwise this would only re-test the signature check.
        stale = int(time.time()) - SESSION_LIFETIME_S - 1
        from app.backend.services.console_auth import _sign  # noqa: PLC0415

        expired = f"{version}.{stale}.{_sign('seed-secret', f'{version}.{stale}')}"

        assert await service.session_is_valid(expired) is False

    @pytest.mark.asyncio
    async def test_changing_the_password_invalidates_existing_sessions(
        self, service: ConsoleAuthService
    ) -> None:
        # The property someone changing their password after a scare is relying
        # on. Without it, a change would secure future logins and leave every
        # current session — possibly on a device they no longer hold — untouched.
        await service.set_password(PASSWORD, current_password=None)
        cookie = await service.issue_session()

        await service.set_password("a different password", current_password=PASSWORD)

        assert await service.session_is_valid(cookie) is False

    @pytest.mark.asyncio
    async def test_a_session_issued_after_the_change_is_valid(
        self, service: ConsoleAuthService
    ) -> None:
        await service.set_password(PASSWORD, current_password=None)
        await service.set_password("a different password", current_password=PASSWORD)

        assert await service.session_is_valid(await service.issue_session()) is True


class TestClearingThePassword:
    @pytest.mark.asyncio
    async def test_returns_the_console_to_open(self, service: ConsoleAuthService) -> None:
        await service.set_password(PASSWORD, current_password=None)

        await service.clear_password()

        assert (await service.state()).password_set is False

    @pytest.mark.asyncio
    async def test_invalidates_existing_sessions(self, service: ConsoleAuthService) -> None:
        await service.set_password(PASSWORD, current_password=None)
        cookie = await service.issue_session()

        await service.clear_password()

        assert await service.session_is_valid(cookie) is False
