"""Async database engine, session factory, and the WAL durability pragmas (ADR-0005).

This is the only module that constructs the SQLAlchemy engine. The database
URL always comes from `Settings.database_url` (never hard-coded) so production
can point at a Docker volume and tests can point at a temp file interchangeably.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.backend.config import Settings


def _enable_sqlite_durability_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Set the WAL/durability PRAGMAs on every new DBAPI connection (ADR-0005).

    Registered on the sync `Engine.connect` event, which SQLAlchemy's async
    dialects still fire per underlying DBAPI connection — so this runs for
    every pooled connection, not just the first, which matters because
    `PRAGMA journal_mode` and `synchronous` are per-connection state in
    `aiosqlite`/`sqlite3`.

    - `journal_mode = WAL`: survives a power cut mid-write; readers never
      block the writer (the SSE loop reads continuously).
    - `synchronous = NORMAL`: safe specifically because WAL frames are
      checksummed — the worst case on an OS crash is losing the last
      transaction, never corruption. Must not be separated from WAL.
    - `busy_timeout = 5000`: a brief wait instead of `SQLITE_BUSY` under
      concurrent SSE reads and an operator PATCH.
    - `foreign_keys = ON`: SQLite disables FK enforcement by default.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


def create_sentry_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine for `settings.database_url`, wired for WAL durability.

    Kept as a factory (rather than a module-level singleton) so tests can
    build an isolated engine per temp database without import-order coupling
    to the process-wide `Settings`.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    # `event.listens_for` targets the *sync* Engine that backs the async one
    # (`engine.sync_engine`) — the async dialect delegates connection-pool
    # events to it, and this is the documented hook point for per-connection
    # PRAGMAs under `sqlalchemy.ext.asyncio`.
    event.listen(engine.sync_engine, "connect", _enable_sqlite_durability_pragmas)
    return engine


def create_sentry_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory bound to `engine`.

    `expire_on_commit=False` so a row returned from a repository method
    remains readable after its transaction commits, without a redundant
    round-trip refresh.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session_from_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session from `session_factory`, closing it after use.

    Intended to be partially applied (`functools.partial` or a small lambda)
    into a FastAPI `Depends` per the composition root's wiring in `main.py`,
    since the factory itself is built once from `Settings` at startup.
    """
    async with session_factory() as session:
        yield session


__all__ = [
    "Engine",
    "create_sentry_engine",
    "create_sentry_session_factory",
    "get_session_from_factory",
]
