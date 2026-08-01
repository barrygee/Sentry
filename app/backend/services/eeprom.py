"""The guarded `rtl_eeprom -s` flow (architecture §4.3, §7.6, ADR-0003).

Validates the requested serial's charset, asserts the device is idle, takes a
per-device lock, stops the pair, execs `rtl_eeprom` with a list argv (never a
shell string), parses the result, migrates the persisted identity, and marks
`requires_replug`. The heaviest guard set in the codebase — this is the
primary reason `SENTRY_AUTH_TOKEN` exists as an option.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Literal

from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.schemas.events import NoticeItem
from app.backend.schemas.serial import SERIAL_PATTERN
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.event_bus import EventBus, SseMessage
from app.backend.services.supervisor import IndexResolutionError, SupervisorService

_logger = logging.getLogger(__name__)

SERIAL_FLASH_TIMEOUT_S = 30.0
STDERR_TRUNCATE_CHARS = 500
PENDING_REPLUG_WINDOW_S = 120.0
"""How long an absent device's alarm is suppressed after a successful flash."""

_SERIAL_CHARSET = re.compile(SERIAL_PATTERN)
"""Re-checked here even though `schemas.serial.SerialFlashRequest` already
enforces this pattern at the Pydantic edge — this service is invoked from a
background task, one hop removed from that validated request, so it never
trusts that the caller re-validated instead of re-checking for itself
(architecture §7.6 guard 1: re-asserted, not merely assumed)."""

# A device must be idle (not actively streaming/starting) before its EEPROM
# can be written — the same set `routers/devices.py` pre-checks, re-asserted
# here under the per-device reservation rather than trusted from that earlier,
# now-stale check (architecture §7.6 guard 4).
_IDLE_STATES = frozenset({"detected", "configured", "stopped"})

_FALLBACK_SPAWN_PATH = "/usr/local/bin:/usr/bin:/bin"
"""Same fallback `SupervisorService` uses (see that module's `_rtl_tcp_env`) —
`rtl_eeprom_path` defaults to the bare name `"rtl_eeprom"`, resolved by the
*child's* `PATH`; an empty spawn environment would hit the exact same
`FileNotFoundError` bug finding #5 identified for `rtl_tcp` (the binary
lives in `/usr/local/bin` in the runtime image, not the empty-env fallback
of `/bin:/usr/bin`)."""

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
    """Executes the guarded serial-flash operation for one device at a time.

    **Process-wide reservation, not a per-device lock alone.** Two requests
    flashing the *same* serial to two *different* devices would both pass a
    naive per-device-only guard and both succeed, recreating the exact
    duplicate-serial condition this feature exists to remedy — so
    `begin_flash()` reserves both `device_id` *and* `serial` atomically
    (`_locked_devices`/`_reserved_serials`), process-wide, for the whole
    duration of one flash.
    """

    def __init__(
        self,
        process_spawner: ProcessSpawner,
        rtlsdr_library: RtlSdrLibrary,
        supervisor: SupervisorService,
        device_registry: DeviceRegistry,
        rtl_eeprom_path: str,
        event_bus: EventBus,
    ) -> None:
        self._process_spawner = process_spawner
        self._rtlsdr_library = rtlsdr_library
        self._supervisor = supervisor
        self._device_registry = device_registry
        self._rtl_eeprom_path = rtl_eeprom_path
        self._event_bus = event_bus
        self._locked_devices: set[str] = set()
        self._reserved_serials: set[str] = set()

    def is_locked(self, device_id: str) -> bool:
        """Return whether a flash is currently reserved/in progress for `device_id`."""
        return device_id in self._locked_devices

    def begin_flash(self, device_id: str, serial: str) -> SerialFlashFailure | None:
        """Atomically reserve `device_id` and `serial` for one flash, or say why not.

        **Must be called synchronously in the router handler**, before
        `create_task(flash_serial(...))` — the previous `is_locked()` check
        followed by a separate `create_task()` call was not atomic: two
        concurrent requests could both observe "not locked" and both
        dispatch a flash. This method contains no `await` at all, so it is
        atomic with respect to every other coroutine (asyncio only switches
        tasks at an `await` point) — two concurrent calls can never both
        succeed for the same device or the same serial.

        Returns `None` on success (the caller now owns this reservation and
        must eventually call `flash_serial()`, which always releases it, even
        on failure) or the specific rejection code otherwise.
        """
        if device_id in self._locked_devices:
            return "device_busy"
        if serial in self._reserved_serials:
            return "serial_in_use"
        self._locked_devices.add(device_id)
        self._reserved_serials.add(serial)
        return None

    def _release(self, device_id: str, serial: str) -> None:
        """Release a reservation made by `begin_flash`. Idempotent."""
        self._locked_devices.discard(device_id)
        self._reserved_serials.discard(serial)

    async def flash_serial(self, device_id: str, serial: str, operation_id: str) -> None:
        """Run the full guarded flash flow for `device_id`, publishing the outcome as a notice.

        Assumes the caller already reserved `(device_id, serial)` via
        `begin_flash()` — this method always releases that reservation
        before returning, on every path, success or failure.

        Guards enforced before any hardware write: charset allow-list
        (re-checked, not trusted), device idle
        (`detected`/`configured`/`stopped`, re-checked against live state),
        and the pair actively stopped under the supervisor's own per-device
        lock (`SupervisorService.stop_device`) so a concurrent `PATCH
        {"enabled": true}` or hotplug arrival cannot leave `rtl_tcp` holding
        the dongle open while `rtl_eeprom` writes to it.
        """
        try:
            await self._run_guarded_flash(device_id, serial, operation_id)
        finally:
            self._release(device_id, serial)

    async def _run_guarded_flash(self, device_id: str, serial: str, operation_id: str) -> None:
        """The guarded flash body — see `flash_serial` for the guard list."""
        if not _SERIAL_CHARSET.fullmatch(serial):
            self._publish_outcome(operation_id, device_id, False, "invalid_serial")
            return

        status = self._device_registry.get_status(device_id)
        if status is None:
            self._publish_outcome(operation_id, device_id, False, "flash_failed")
            return
        if status.needs_identification:
            self._publish_outcome(operation_id, device_id, False, "device_unidentified")
            return
        if status.state not in _IDLE_STATES:
            self._publish_outcome(operation_id, device_id, False, "device_busy")
            return

        raw_serial = status.usb.serial if status.usb is not None else None
        if raw_serial is None and status.usb_last_known is not None:
            raw_serial = status.usb_last_known.serial
        if not raw_serial:
            # No live or last-known raw serial to resolve a librtlsdr index
            # from — this device cannot be flashed right now regardless of
            # its lifecycle state (e.g. a tier-2 device with an empty
            # descriptor serial).
            self._publish_outcome(operation_id, device_id, False, "device_busy")
            return

        # Guarantee `rtl_tcp` has actually released the USB device before
        # `rtl_eeprom` opens it — taken under the supervisor's own per-device
        # lock, so this cannot race a concurrent spawn for the same device.
        await self._supervisor.stop_device(device_id, "eeprom_flash")

        try:
            resolved_index = await self._supervisor.resolve_spawn_index(raw_serial)
        except IndexResolutionError as error:
            self._publish_outcome(
                operation_id, device_id, False, "flash_failed", stderr_tail=str(error)
            )
            return

        # Always a list argv, never a shell string (architecture §7.6, §12.7,
        # §12.10) — `serial` is passed as one argv element regardless of its
        # content, so it can never be interpreted as anything but the
        # literal `-s` value even if the charset check above were somehow
        # bypassed.
        argv = [self._rtl_eeprom_path, "-d", str(resolved_index), "-s", serial]
        spawn_env = {"PATH": os.environ.get("PATH", _FALLBACK_SPAWN_PATH)}
        try:
            process = await self._process_spawner.spawn(
                argv, spawn_env, name=f"{device_id}-rtl_eeprom", capture_output=True
            )
        except OSError as error:
            self._publish_outcome(
                operation_id, device_id, False, "rtl_eeprom_unavailable", stderr_tail=str(error)
            )
            return

        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=SERIAL_FLASH_TIMEOUT_S)
        except TimeoutError:
            process.kill()
            self._publish_outcome(
                operation_id,
                device_id,
                False,
                "flash_failed",
                stderr_tail=f"rtl_eeprom did not exit within {SERIAL_FLASH_TIMEOUT_S:.0f}s",
            )
            return

        _stdout, stderr = await process.communicate()
        stderr_tail = stderr.decode("utf-8", errors="replace")[-STDERR_TRUNCATE_CHARS:]
        if exit_code != 0:
            self._publish_outcome(
                operation_id, device_id, False, "flash_failed", stderr_tail=stderr_tail or None
            )
            return

        migrated = await self._device_registry.migrate_identity_after_flash(
            device_id, serial, PENDING_REPLUG_WINDOW_S
        )
        if migrated is None:
            _logger.warning(
                "eeprom flash for %s succeeded but the device had no persisted "
                "configuration to migrate (operation_id=%s)",
                device_id,
                operation_id,
            )
        self._publish_outcome(operation_id, device_id, True)

    def _publish_outcome(
        self,
        operation_id: str,
        device_id: str,
        succeeded: bool,
        failure_code: SerialFlashFailure | None = None,
        stderr_tail: str | None = None,
    ) -> None:
        """Publish one flash's terminal outcome as both a typed record and an SSE `notice`.

        The `notice` is the only channel `POST .../serial`'s `202 Accepted`
        contract promises the outcome arrives on (architecture §7.6) — there
        is no separate polling endpoint.
        """
        outcome = SerialFlashOutcome(
            operation_id=operation_id,
            succeeded=succeeded,
            failure_code=failure_code,
            stderr_tail=stderr_tail[-STDERR_TRUNCATE_CHARS:] if stderr_tail else None,
        )
        if outcome.succeeded:
            message = f"Serial flash succeeded for {device_id}; replug the device to apply it."
            level = "info"
        else:
            message = f"Serial flash failed for {device_id}: {outcome.failure_code}."
            level = "error"
        self._event_bus.publish(
            SseMessage(
                event="notice",
                data=NoticeItem(
                    level=level,  # type: ignore[arg-type]
                    code=outcome.failure_code or "serial_flash_succeeded",
                    message=message,
                    device_id=device_id,
                    ts=self._now_ms(),
                ),
            )
        )
        _logger.info(
            "serial flash outcome device_id=%s operation_id=%s succeeded=%s failure_code=%s",
            device_id,
            operation_id,
            outcome.succeeded,
            outcome.failure_code,
        )

    def _now_ms(self) -> int:
        """Unix ms for the published notice's timestamp.

        `EepromService`'s composition-root constructor signature (`main.py`)
        was frozen without a direct `Clock` dependency; rather than widen
        that frozen shape, this mirrors `HealthService`'s already-precedented
        exception (see that module's docstring) and reads wall time
        directly — a single timestamp read, with no sleep/backoff logic
        riding on it.
        """
        return int(time.time() * 1000)
