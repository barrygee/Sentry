"""Reads and writes this Sentry's fixed position (the `sentry_location` row).

Modelled on `HostControlSettingsService`: one single-row table, every read
hitting the database rather than a cached value. The position is read on
`GET /api/status` and `GET /api/v1/sdrs` — both of which Sentinel polls — but
that is one indexed read from a local SQLite file per poll, against a cache
that would have to be invalidated across the whole container to stay correct.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backend.interfaces.clock import Clock
from app.backend.models import SentryLocationModel
from app.backend.schemas.location import SentryLocation

LOCATION_ROW_ID = 1
"""`sentry_location` is a single row, seeded by migration 0006."""


class SentryLocationService:
    """Reads and writes the single `sentry_location` row."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def get_location(self) -> SentryLocation:
        """Return the stored position, or an unset one if none has been set."""
        async with self._session_factory() as session:
            row = await self._row(session)
            return SentryLocation(
                latitude=row.latitude,
                longitude=row.longitude,
                updated_at=row.updated_at,
            )

    async def set_location(self, latitude: float | None, longitude: float | None) -> SentryLocation:
        """Store a position, or clear it when both coordinates are `None`.

        Callers pass a pair that `SentryLocationUpdate` has already validated as
        both-or-neither, so there is no half-set state to guard against here.
        """
        async with self._session_factory() as session:
            row = await self._row(session)
            row.latitude = latitude
            row.longitude = longitude
            row.updated_at = self._clock.now_ms()
            await session.commit()
            return SentryLocation(
                latitude=row.latitude,
                longitude=row.longitude,
                updated_at=row.updated_at,
            )

    async def _row(self, session: AsyncSession) -> SentryLocationModel:
        """Return the single location row, which migration 0006 guarantees exists."""
        result = await session.execute(
            select(SentryLocationModel).where(SentryLocationModel.id == LOCATION_ROW_ID)
        )
        row = result.scalar_one_or_none()
        if row is None:
            # Only reachable on a database the migration did not touch. Creating
            # it unset here beats a 500 on `/api/status`, which is polled.
            row = SentryLocationModel(
                id=LOCATION_ROW_ID, latitude=None, longitude=None, updated_at=0
            )
            session.add(row)
            await session.commit()
        return row
