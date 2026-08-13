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
from app.backend.schemas.events import NoticeItem
from app.backend.services.event_bus import EventBus, SseMessage
from app.backend.services.sentry_location import SentryLocationService

from ..fakes.clock import FakeClock

LATITUDE = 54.95149
LONGITUDE = -1.53586


class RecordingEventBus(EventBus):
    """An `EventBus` that keeps what was published, rather than fanning it out.

    Subclassed rather than mocked so the service is still handed the real type:
    a stub that drifted from `EventBus.publish`'s signature would pass here and
    fail in production, which is the one thing this test exists to prevent.
    """

    def __init__(self, clock: FakeClock | None = None) -> None:
        super().__init__(clock or FakeClock())
        self.published: list[SseMessage] = []

    def publish(self, message: SseMessage) -> None:
        self.published.append(message)

    def notices(self) -> list[NoticeItem]:
        return [
            message.data
            for message in self.published
            if message.event == "notice" and isinstance(message.data, NoticeItem)
        ]


def build_service(
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock | None = None,
    event_bus: EventBus | None = None,
) -> SentryLocationService:
    resolved_clock = clock or FakeClock()
    return SentryLocationService(
        session_factory, resolved_clock, event_bus or EventBus(resolved_clock)
    )


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
        service = build_service(session_factory)

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
        writer = build_service(session_factory)
        reader = build_service(session_factory)
        await reader.get_location()

        await writer.set_location(LATITUDE, LONGITUDE)

        assert (await reader.get_location()).latitude == LATITUDE


class TestWritingThePosition:
    @pytest.mark.asyncio
    async def test_stores_both_coordinates(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = build_service(session_factory)

        saved = await service.set_location(LATITUDE, LONGITUDE)

        assert (saved.latitude, saved.longitude) == (LATITUDE, LONGITUDE)
        assert (await service.get_location()).longitude == LONGITUDE

    @pytest.mark.asyncio
    async def test_stamps_the_time_it_changed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        clock = FakeClock(start_ms=1_700_000_000_000)
        service = build_service(session_factory, clock)

        saved = await service.set_location(LATITUDE, LONGITUDE)

        assert saved.updated_at == clock.now_ms()

    @pytest.mark.asyncio
    async def test_clearing_really_clears_both_coordinates(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # The failure this guards against is a "clear" that only nulls one
        # column, leaving a half-pair the schema would then refuse to load.
        service = build_service(session_factory)
        await service.set_location(LATITUDE, LONGITUDE)

        cleared = await service.set_location(None, None)

        assert cleared.latitude is None
        assert cleared.longitude is None
        assert (await service.get_location()).is_set is False

    @pytest.mark.asyncio
    async def test_overwrites_rather_than_inserting_a_second_row(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = build_service(session_factory)

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
        service = build_service(unseeded_session_factory)

        location = await service.get_location()

        assert location.is_set is False

    @pytest.mark.asyncio
    async def test_writing_still_lands(
        self, unseeded_session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = build_service(unseeded_session_factory)

        await service.set_location(LATITUDE, LONGITUDE)

        assert (await service.get_location()).latitude == LATITUDE


class TestTheNoticeItPublishes:
    """The console shows a stored position through the app-wide notice log.

    Published for every writer, not just the panel: a config import or another
    browser moving the Sentry is precisely the change an operator would
    otherwise never see.
    """

    @pytest.mark.asyncio
    async def test_announces_a_stored_position(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        event_bus = RecordingEventBus()
        service = build_service(session_factory, event_bus=event_bus)

        await service.set_location(LATITUDE, LONGITUDE)

        notices = event_bus.notices()
        assert len(notices) == 1
        assert notices[0].code == "location_set"
        assert str(LATITUDE) in notices[0].message

    @pytest.mark.asyncio
    async def test_announces_a_cleared_position_differently(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        event_bus = RecordingEventBus()
        service = build_service(session_factory, event_bus=event_bus)

        await service.set_location(None, None)

        assert event_bus.notices()[0].code == "location_cleared"

    @pytest.mark.asyncio
    async def test_the_notice_is_instance_wide_not_per_device(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # `device_id=None` is what puts it in the Settings notice list rather
        # than against a dongle it has nothing to do with.
        event_bus = RecordingEventBus()
        service = build_service(session_factory, event_bus=event_bus)

        await service.set_location(LATITUDE, LONGITUDE)

        assert event_bus.notices()[0].device_id is None

    @pytest.mark.asyncio
    async def test_reading_the_position_announces_nothing(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # `/api/status` is polled; a notice per read would bury the log.
        event_bus = RecordingEventBus()
        service = build_service(session_factory, event_bus=event_bus)

        await service.get_location()

        assert event_bus.notices() == []
