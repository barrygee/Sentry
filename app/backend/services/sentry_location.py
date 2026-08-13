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
from app.backend.schemas.events import NoticeItem
from app.backend.schemas.location import SentryLocation
from app.backend.services.event_bus import EventBus, SseMessage

LOCATION_ROW_ID = 1
"""`sentry_location` is a single row, seeded by migration 0006."""


class SentryLocationService:
    """Reads and writes the single `sentry_location` row."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        event_bus: EventBus,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._event_bus = event_bus

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
            saved = SentryLocation(
                latitude=row.latitude,
                longitude=row.longitude,
                updated_at=row.updated_at,
            )
        # Published after the commit, so a notice can never announce a position
        # that failed to store. Announced for *every* writer — the panel, the
        # `PUT`/`POST` endpoint and a config import alike — because a location
        # changing under an operator's feet is exactly what the notice log is
        # for, and a browser that did not make the change is the one that most
        # needs telling.
        self._publish_saved_notice(saved)
        return saved

    def _publish_saved_notice(self, saved: SentryLocation) -> None:
        """Announce a position change on the existing SSE `notice` event.

        Reuses `notice` rather than adding an event name, exactly as the hotspot
        does: `_PUBLIC_EVENT_NAMES` in `routers/events.py` stays untouched, so
        every existing client tolerates this without a change.

        The console renders it through the same dismissible notice log that
        carries "Hotspot is up on wlan0." — which is why this panel has no
        confirmation banner of its own. One mechanism for "something happened",
        dismissed one way, wherever it came from.
        """
        message = (
            f"Sentry location set to {saved.latitude}, {saved.longitude}."
            if saved.is_set
            else "Sentry location cleared. Sentinel can no longer plot this Sentry."
        )
        self._event_bus.publish(
            SseMessage(
                event="notice",
                data=NoticeItem(
                    level="info",
                    code="location_set" if saved.is_set else "location_cleared",
                    message=message,
                    device_id=None,
                    ts=self._clock.now_ms(),
                ),
            )
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
