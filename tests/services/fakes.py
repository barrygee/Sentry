"""Fakes for the two seams `port_allocator` and `supervisor` depend on.

Hand-written rather than `unittest.mock`: both need to record *how many times*
they were called, and the allocator's whole performance contract is expressed in
that count — "fetch the reserved pairs once per search, not once per candidate"
is invisible to a mock that only remembers the last call.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.backend.interfaces.types import PersistedDeviceRow


def device_row(
    *,
    record_id: int = 1,
    identity_kind: Literal["serial", "usb"] = "serial",
    identity_key: str = "AIS-01",
    output_port: int = 1234,
    enabled: bool = True,
    name: str = "AIS SDR",
) -> PersistedDeviceRow:
    """One persisted row, with only the fields these tests care about spelled out."""
    return PersistedDeviceRow(
        id=record_id,
        identity_kind=identity_kind,
        identity_key=identity_key,
        name=name,
        description="",
        notes="",
        antenna="",
        output_port=output_port,
        enabled=enabled,
        visibility="public",
        center_hz=None,
        sample_rate=None,
        gain_db=None,
        gain_auto=True,
        ppm_correction=0,
        bias_tee=None,
        direct_sampling=None,
        last_topology_path="",
        last_vendor_id="",
        last_product_id="",
        last_manufacturer="",
        last_product="",
        last_serial="",
        last_seen_at=None,
        pending_replug_until=None,
        created_at=0,
        updated_at=0,
    )


class FakePortProber:
    """A `PortProber` whose answers are scripted per port."""

    def __init__(self, unbindable_ports: frozenset[int] = frozenset()) -> None:
        self._unbindable_ports = unbindable_ports
        self.probed_ports: list[int] = []

    def is_bindable(self, host: str, port: int) -> bool:
        self.probed_ports.append(port)
        return port not in self._unbindable_ports


class FakeDeviceRepository:
    """A `DeviceRepository` over an in-memory list, counting `list_all()` calls."""

    def __init__(self, rows: Sequence[PersistedDeviceRow] = ()) -> None:
        self.rows = list(rows)
        self.list_all_call_count = 0

    async def get_by_identity(
        self, identity_kind: str, identity_key: str
    ) -> PersistedDeviceRow | None:
        for row in self.rows:
            if row.identity_kind == identity_kind and row.identity_key == identity_key:
                return row
        return None

    async def get_by_record_id(self, record_id: int) -> PersistedDeviceRow | None:
        for row in self.rows:
            if row.id == record_id:
                return row
        return None

    async def list_all(self) -> Sequence[PersistedDeviceRow]:
        self.list_all_call_count += 1
        return list(self.rows)

    async def upsert(self, row: PersistedDeviceRow) -> PersistedDeviceRow:
        self.rows = [existing for existing in self.rows if existing.id != row.id]
        self.rows.append(row)
        return row

    async def delete(self, record_id: int) -> None:
        self.rows = [existing for existing in self.rows if existing.id != record_id]
