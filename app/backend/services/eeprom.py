"""The guarded `rtl_eeprom -s` flow (architecture §4.3, §7.6, ADR-0003).

Validates the requested serial's charset, asserts the device is idle, takes a
per-device lock, stops the pair, execs `rtl_eeprom` with a list argv (never a
shell string), parses the result, migrates the persisted identity, and marks
`requires_replug`. The heaviest guard set in the codebase — this is the
primary reason `SENTRY_AUTH_TOKEN` exists as an option.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.supervisor import SupervisorService

SERIAL_FLASH_TIMEOUT_S = 30.0
STDERR_TRUNCATE_CHARS = 500
PENDING_REPLUG_WINDOW_S = 120.0
"""How long an absent device's alarm is suppressed after a successful flash."""

SerialFlashFailure = Literal[
    "invalid_serial",
    "device_busy",
    "serial_in_use",
    "device_unidentified",
    "rtl_eeprom_unavailable",
    "flash_failed",
]


@dataclass(frozen=True, slots=True)
class SerialFlashOutcome:
    """The final result of one serial-flash operation, delivered via an SSE `notice`."""

    operation_id: str
    succeeded: bool
    failure_code: SerialFlashFailure | None = None
    stderr_tail: str | None = None
    """Truncated to `STDERR_TRUNCATE_CHARS`; never echoed as HTML."""


class EepromService:
    """Executes the guarded serial-flash operation for one device at a time."""

    def __init__(
        self,
        process_spawner: ProcessSpawner,
        rtlsdr_library: RtlSdrLibrary,
        supervisor: SupervisorService,
        device_registry: DeviceRegistry,
        rtl_eeprom_path: str,
    ) -> None:
        self._process_spawner = process_spawner
        self._rtlsdr_library = rtlsdr_library
        self._supervisor = supervisor
        self._device_registry = device_registry
        self._rtl_eeprom_path = rtl_eeprom_path

    async def flash_serial(self, device_id: str, serial: str, operation_id: str) -> None:
        """Run the full guarded flash flow for `device_id`, publishing the outcome as a notice.

        Guards enforced before any hardware write: charset allow-list,
        uniqueness against every other known serial/identity_key, device
        idle (`detected`/`configured`/`stopped`), and a per-device lock so
        hotplug cannot respawn a pair mid-write and two flashes cannot race.
        """
        raise NotImplementedError

    def is_locked(self, device_id: str) -> bool:
        """Return whether a flash is currently in progress for `device_id`."""
        raise NotImplementedError
