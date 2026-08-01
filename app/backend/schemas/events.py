"""SSE payload shapes for `GET /api/events` (architecture §7.3).

Each named SSE event's `data:` field is one of these models serialized to
JSON — there is no wrapper envelope; the event name itself (`snapshot`,
`device_changed`, `device_removed`, `health`, `notice`) carries the
discriminant.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NoticeLevel = Literal["info", "warn", "error"]


class NoticeItem(BaseModel):
    """One operator-facing notice: serial-flash progress, spawn failures, conflicts."""

    model_config = ConfigDict(frozen=True)

    level: NoticeLevel
    code: str = Field(description="Machine code, e.g. port_conflict, driver_conflict")
    message: str
    device_id: str | None = None
    ts: int = Field(description="Unix ms")


class DeviceRemovedEvent(BaseModel):
    """SSE `device_removed`: a device's row/identity was removed from the registry.

    The common case is an *unconfigured* (never-persisted) device being
    unplugged — a configured, still-present device instead transitions to
    `state: "stopped"`, `present: false` via `device_changed`. But
    `DeviceRegistry.delete()` also emits this event for a configured device
    whose row was deleted while it was already absent, so this event is not
    exclusively the unconfigured-device case.
    """

    model_config = ConfigDict(frozen=True)

    device_id: str
    record_id: int | None = None
