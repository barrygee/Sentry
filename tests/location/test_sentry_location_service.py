"""Tests for `SentryLocationService` — the single `sentry_location` row.

The properties worth asserting are the ones that would be quietly wrong:
the row is read fresh rather than cached, clearing a position really clears it
(rather than leaving a stale coordinate behind), and a database the migration
never touched self-heals instead of 500ing a polled endpoint.

Run with:  uv run pytest tests/location/test_sentry_location_service.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.backend.models import Base, SentryLocationModel
from app.backend.services.sentry_location import SentryLocationService

from ..fakes.clock import FakeClock

LATITUDE = 54.95149
LONGITUDE = -1.53586


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A throwaway SQLite file with the single location row seeded, as migration 0006 does."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'location.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(SentryLocationModel(id=1, latitude=None, longitude=None, updated_at=0))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def unseeded_session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The same schema with **no** row — a database the migration never seeded."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unseeded.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestReadingThePosition:
    @pytest.mark.asyncio
    async def test_a_fresh_install_reports_no_position(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = SentryLocationService(session_factory, FakeClock())

        location = await service.get_location()

        assert location.latitude is None
        assert location.longitude is None
        assert location.updated_at == 0

    @pytest.mark.asyncio
    async def test_reads_the_row_fresh_rather_than_a_cached_value(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # Two services over one database stand in for the two workers/processes
        # that could hold a cache. `/api/status` is polled, so a stale read here
        # would strand Sentinel on an old position indefinitely.
        writer = SentryLocationService(session_factory, FakeClock())
        reader = SentryLocationService(session_factory, FakeClock())
        await reader.get_location()

        await writer.set_location(LATITUDE, LONGITUDE)

        assert (await reader.get_location()).latitude == LATITUDE


class TestWritingThePosition:
    @pytest.mark.asyncio
    async def test_stores_both_coordinates(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = SentryLocationService(session_factory, FakeClock())

        saved = await service.set_location(LATITUDE, LONGITUDE)

        assert (saved.latitude, saved.longitude) == (LATITUDE, LONGITUDE)
        assert (await service.get_location()).longitude == LONGITUDE

    @pytest.mark.asyncio
    async def test_stamps_the_time_it_changed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        clock = FakeClock(start_ms=1_700_000_000_000)
        service = SentryLocationService(session_factory, clock)

        saved = await service.set_location(LATITUDE, LONGITUDE)

        assert saved.updated_at == clock.now_ms()

    @pytest.mark.asyncio
    async def test_clearing_really_clears_both_coordinates(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # The failure this guards against is a "clear" that only nulls one
        # column, leaving a half-pair the schema would then refuse to load.
        service = SentryLocationService(session_factory, FakeClock())
        await service.set_location(LATITUDE, LONGITUDE)

        cleared = await service.set_location(None, None)

        assert cleared.latitude is None
        assert cleared.longitude is None
        assert (await service.get_location()).is_set is False

    @pytest.mark.asyncio
    async def test_overwrites_rather_than_inserting_a_second_row(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = SentryLocationService(session_factory, FakeClock())

        await service.set_location(LATITUDE, LONGITUDE)
        await service.set_location(1.0, 2.0)

        async with session_factory() as session:
            rows = (await session.execute(select(SentryLocationModel))).scalars().all()
        assert len(rows) == 1
        assert rows[0].latitude == 1.0


class TestAnUnseededDatabase:
    """Only reachable on a database the migration did not touch — it must not 500."""

    @pytest.mark.asyncio
    async def test_reading_creates_the_row_unset(
        self, unseeded_session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = SentryLocationService(unseeded_session_factory, FakeClock())

        location = await service.get_location()

        assert location.is_set is False

    @pytest.mark.asyncio
    async def test_writing_still_lands(
        self, unseeded_session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = SentryLocationService(unseeded_session_factory, FakeClock())

        await service.set_location(LATITUDE, LONGITUDE)

        assert (await service.get_location()).latitude == LATITUDE
