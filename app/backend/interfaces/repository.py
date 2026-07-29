"""Persistence seam for the single `sdr_devices` table (architecture §6, §4.3).

Not one of the hardware-edge Protocols enumerated in architecture §4.1, but
the same discipline applies: `device_registry` and `port_allocator` depend on
this narrow Protocol rather than importing SQLAlchemy directly, so both are
unit-testable against an in-memory fake with no database. The
database-engineer's concrete `repositories.device_repository.DeviceRepository`
(Phase 1B) is expected to satisfy this shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.backend.interfaces.types import PersistedDeviceRow


@runtime_checkable
class DeviceRepository(Protocol):
    """CRUD access to persisted device configuration — the only writer of `sdr_devices`."""

    async def get_by_identity(
        self, identity_kind: str, identity_key: str
    ) -> PersistedDeviceRow | None:
        """Return the row keyed by `(identity_kind, identity_key)`, or None if unconfigured."""
        ...

    async def get_by_record_id(self, record_id: int) -> PersistedDeviceRow | None:
        """Return the row with this surrogate key, or None if it does not exist."""
        ...

    async def list_all(self) -> Sequence[PersistedDeviceRow]:
        """Return every persisted device row, configured or not currently present."""
        ...

    async def upsert(self, row: PersistedDeviceRow) -> PersistedDeviceRow:
        """Insert a new row or update the existing one matching `row`'s identity key.

        Raises an adapter-appropriate error (mapped by the router to `409
        port_conflict` / `409 name_conflict`) on a unique-index violation.
        """
        ...

    async def delete(self, record_id: int) -> None:
        """Remove a persisted row by its surrogate key. Idempotent if already absent."""
        ...

    async def list_reserved_port_pairs(self) -> Sequence[tuple[int, int]]:
        """Return every `(output_port, output_port + 2)` pair currently reserved.

        Includes disabled and absent devices — their reservations still block
        a new assignment (architecture §8 rule 2).
        """
        ...
