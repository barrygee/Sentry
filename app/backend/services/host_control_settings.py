"""The operator-flippable host capability switches (ADR-0013).

`SENTRY_HOTSPOT_CONTROL_ENABLED` used to be the only way to turn hotspot control
on, which meant the console's own instructions for enabling a feature it fully
manages were "open a terminal, append a line, restart the container". This
service holds the same switch in the database instead, so the UI can flip it.

The environment variable still works, and still wins. An operator who set it is
relying on it; a database row quietly overriding it would be the reverse of the
guarantee `.env` is supposed to give.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backend.interfaces.clock import Clock
from app.backend.models import HostControlSettingsModel

SETTINGS_ROW_ID = 1
"""`host_control_settings` is a single row, seeded by migration 0005."""


class HostControlSettingsService:
    """Reads and writes the single `host_control_settings` row.

    Every read hits the database rather than a cached value. The switch is
    checked on hotspot calls only — not on any hot path — and a cache here would
    have to be invalidated across the whole container, which is a lot of
    machinery to save a single indexed read from a local SQLite file.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        *,
        forced_hotspot_control_enabled: bool,
    ) -> None:
        """`forced_hotspot_control_enabled` is `SENTRY_HOTSPOT_CONTROL_ENABLED`.

        When true it overrides the stored value permanently — see
        `hotspot_control_enabled`.
        """
        self._session_factory = session_factory
        self._clock = clock
        self._forced_hotspot_control_enabled = forced_hotspot_control_enabled

    @property
    def hotspot_control_is_forced(self) -> bool:
        """Whether `.env` pins hotspot control on, making the stored value moot.

        Surfaced to the UI so the toggle can explain itself instead of appearing
        broken: a switch that refuses to move and says nothing is worse than no
        switch at all.
        """
        return self._forced_hotspot_control_enabled

    async def hotspot_control_enabled(self) -> bool:
        """Whether the API may reconfigure this host's WiFi, right now.

        `.env` OR the stored value. The environment variable can only enable,
        never disable — an operator who put it there is depending on it, and a
        UI toggle silently overriding a deploy-time decision would defeat the
        point of having one.
        """
        if self._forced_hotspot_control_enabled:
            return True
        return await self._stored_hotspot_control_enabled()

    async def _stored_hotspot_control_enabled(self) -> bool:
        async with self._session_factory() as session:
            row = await self._row(session)
            return row.hotspot_control_enabled

    async def set_hotspot_control_enabled(self, enabled: bool) -> None:
        """Store `enabled`, whatever `.env` says.

        Deliberately still writes while `.env` forces control on: the stored
        value is what takes effect if that variable is later removed, so
        silently discarding the write would surprise an operator who tidied
        their `.env` months afterwards.
        """
        async with self._session_factory() as session:
            row = await self._row(session)
            row.hotspot_control_enabled = enabled
            row.updated_at = self._clock.now_ms()
            await session.commit()

    async def _row(self, session: AsyncSession) -> HostControlSettingsModel:
        """Return the single settings row, which migration 0005 guarantees exists."""
        result = await session.execute(
            select(HostControlSettingsModel).where(HostControlSettingsModel.id == SETTINGS_ROW_ID)
        )
        row = result.scalar_one_or_none()
        if row is None:
            # Only reachable on a database the migration did not touch. Creating
            # it here beats a 500 on a request that has nothing to do with it.
            row = HostControlSettingsModel(
                id=SETTINGS_ROW_ID, hotspot_control_enabled=False, updated_at=0
            )
            session.add(row)
            await session.commit()
        return row
