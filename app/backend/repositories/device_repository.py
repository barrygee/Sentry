"""The only module that writes `sdr_devices` (architecture §4.4).

Implements the `interfaces.repository.DeviceRepository` Protocol against a
real async SQLAlchemy session, so `device_registry` and `port_allocator`
depend on the narrow Protocol and never import SQLAlchemy directly.

**Insert-vs-update convention (the seam Phase 0 flagged for reconciliation):**
`interfaces.types.PersistedDeviceRow.id` is a non-optional `int` because it is
frozen and shared with the pure `identity`/`device_registry` layers, which
never need to express "no id yet". `upsert()` therefore treats `row.id == 0`
as "insert a new row" (SQLite's `INTEGER PRIMARY KEY AUTOINCREMENT` never
assigns rowid 0), and any other value as "update the existing row with this
surrogate key". The returned `PersistedDeviceRow` always carries the real,
assigned id. This is documented here and in the handoff notes rather than
changed silently, since Phase 2 (`device_registry`) is already coded against
`DeviceRepository`.

**One session per call, not one shared session (2A/2B integration fix).**
`DeviceRegistry` is a process-lifetime singleton whose repository calls are
made both from background tasks (its own hotplug-consumer subscription) and,
indirectly through `PortAllocatorService`, from concurrent HTTP request
handlers. A single long-lived `AsyncSession` handed to one `DeviceRepository`
instance and shared across all of that is unsafe: SQLAlchemy async sessions
are explicitly not safe for concurrent use by more than one coroutine at a
time, and two callers awaiting I/O on the same session can interleave and
corrupt its internal state. Rather than papering over this by hoping nothing
ever actually overlaps, this repository is handed the process-wide
`async_sessionmaker` and opens (and closes) one fresh, short-lived session per
method call — each call is a single, complete unit of work, so this adds no
observable behaviour change, only safety under concurrency. SQLite's
`busy_timeout` PRAGMA (`db.py`) absorbs the resulting serialized writer
access across those short-lived sessions.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backend.interfaces.types import PersistedDeviceRow
from app.backend.models import SdrDeviceModel


class DeviceConflictError(Exception):
    """Raised when an upsert violates a unique index (identity or port).

    Routers (Phase 2B) catch this and map it to `409 port_conflict` /
    `409 name_conflict` per architecture §7.5 — the repository itself never
    knows about HTTP.
    """


def _row_from_model(model: SdrDeviceModel) -> PersistedDeviceRow:
    """Convert a persisted ORM row into the frozen `PersistedDeviceRow` contract."""
    return PersistedDeviceRow(
        id=model.id,
        identity_kind=model.identity_kind,  # type: ignore[arg-type]  # CHECK constraint enforces the literal
        identity_key=model.identity_key,
        name=model.name,
        description=model.description,
        output_port=model.output_port,
        enabled=model.enabled,
        center_hz=model.center_hz,
        sample_rate=model.sample_rate,
        gain_db=model.gain_db,
        gain_auto=model.gain_auto,
        ppm_correction=model.ppm_correction,
        bias_tee=model.bias_tee,
        direct_sampling=model.direct_sampling,
        last_topology_path=model.last_topology_path,
        last_vendor_id=model.last_vendor_id,
        last_product_id=model.last_product_id,
        last_manufacturer=model.last_manufacturer,
        last_product=model.last_product,
        last_serial=model.last_serial,
        last_seen_at=model.last_seen_at,
        pending_replug_until=model.pending_replug_until,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _apply_row_to_model(row: PersistedDeviceRow, model: SdrDeviceModel) -> None:
    """Copy every mutable field from `row` onto `model` in place.

    Excludes `id`, which is either database-assigned (insert) or the lookup
    key (update) and is never itself mutated.
    """
    model.identity_kind = row.identity_kind
    model.identity_key = row.identity_key
    model.name = row.name
    model.description = row.description
    model.output_port = row.output_port
    model.enabled = row.enabled
    model.center_hz = row.center_hz
    model.sample_rate = row.sample_rate
    model.gain_db = row.gain_db
    model.gain_auto = row.gain_auto
    model.ppm_correction = row.ppm_correction
    model.bias_tee = row.bias_tee
    model.direct_sampling = row.direct_sampling
    model.last_topology_path = row.last_topology_path
    model.last_vendor_id = row.last_vendor_id
    model.last_product_id = row.last_product_id
    model.last_manufacturer = row.last_manufacturer
    model.last_product = row.last_product
    model.last_serial = row.last_serial
    model.last_seen_at = row.last_seen_at
    model.pending_replug_until = row.pending_replug_until
    model.created_at = row.created_at
    model.updated_at = row.updated_at


class DeviceRepository:
    """Async SQLAlchemy implementation of `interfaces.repository.DeviceRepository`.

    Shared as a single process-wide instance (unlike a typical per-request
    repository) because its sole caller-facing collaborators —
    `DeviceRegistry` and `PortAllocatorService` — are themselves process-
    lifetime singletons. Safe under concurrent use because every method opens
    its own short-lived `AsyncSession` from `session_factory` rather than
    holding one open across calls (see this module's docstring).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_identity(
        self, identity_kind: str, identity_key: str
    ) -> PersistedDeviceRow | None:
        """Return the row keyed by `(identity_kind, identity_key)`, or None if unconfigured."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(SdrDeviceModel).where(
                    SdrDeviceModel.identity_kind == identity_kind,
                    SdrDeviceModel.identity_key == identity_key,
                )
            )
            model = result.scalar_one_or_none()
            return _row_from_model(model) if model is not None else None

    async def get_by_record_id(self, record_id: int) -> PersistedDeviceRow | None:
        """Return the row with this surrogate key, or None if it does not exist."""
        async with self._session_factory() as session:
            model = await session.get(SdrDeviceModel, record_id)
            return _row_from_model(model) if model is not None else None

    async def list_all(self) -> Sequence[PersistedDeviceRow]:
        """Return every persisted device row, configured or not currently present."""
        async with self._session_factory() as session:
            result = await session.execute(select(SdrDeviceModel))
            return [_row_from_model(model) for model in result.scalars().all()]

    async def upsert(self, row: PersistedDeviceRow) -> PersistedDeviceRow:
        """Insert a new row (`row.id == 0`) or update the existing one at `row.id`.

        Raises `DeviceConflictError` on a unique-index violation (duplicate
        identity or duplicate `output_port`), after rolling back so the
        session is left usable for the caller's next attempt.
        """
        async with self._session_factory() as session:
            model: SdrDeviceModel
            try:
                if row.id == 0:
                    model = SdrDeviceModel()
                    session.add(model)
                else:
                    existing = await session.get(SdrDeviceModel, row.id)
                    if existing is None:
                        # Upserting an id that no longer exists is a caller
                        # bug, not a conflict — surfaced distinctly rather
                        # than silently reinserting under a stale surrogate
                        # key.
                        raise ValueError(f"no persisted device with record_id={row.id}")
                    model = existing
                _apply_row_to_model(row, model)
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise DeviceConflictError(str(error)) from error
            await session.refresh(model)
            return _row_from_model(model)

    async def delete(self, record_id: int) -> None:
        """Remove a persisted row by its surrogate key. Idempotent if already absent."""
        async with self._session_factory() as session:
            model = await session.get(SdrDeviceModel, record_id)
            if model is not None:
                await session.delete(model)
                await session.commit()


__all__ = ["DeviceConflictError", "DeviceRepository"]
