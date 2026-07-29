"""`POST /api/devices/{device_id}/serial` request/response shapes (architecture §7.6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SERIAL_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
"""Strict allow-list for a flashed EEPROM serial — not a deny-list (ADR-0003)."""


class SerialFlashRequest(BaseModel):
    """Request body for flashing a unique serial to a dongle's EEPROM."""

    model_config = ConfigDict(extra="forbid")

    serial: str = Field(pattern=SERIAL_PATTERN)
    confirm: Literal[True] = Field(
        description="Must be exactly true; a destructive hardware write requires explicit intent"
    )


class SerialFlashAccepted(BaseModel):
    """`202 Accepted` body; the outcome arrives later as an SSE `notice`."""

    model_config = ConfigDict(frozen=True)

    device_id: str
    operation_id: str = Field(description="Correlates this request with its SSE notice events")
    status: Literal["in_progress"]
    requires_replug: bool = Field(
        default=True, description="A physical replug is required before the new serial is visible"
    )
