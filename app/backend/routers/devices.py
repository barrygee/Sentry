"""`/api/devices*` — the configuration-centric device surface (architecture §7.4-§7.6).

**DELETE contract (settled, previously open).** Architecture §4.4 names the
route but its exact shape was unspecified; per the task brief this is now
fixed as: `204 No Content`, configuration-removal only, and refused with
`409 device_present` for any device currently plugged in — an operator must
unplug (or the config simply never applies again once unplugged) before its
row can be deleted, so a live pair is never torn down by surprise from this
endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.backend.config import Settings
from app.backend.dependencies import (
    get_device_registry,
    get_eeprom_service,
    get_port_allocator,
    get_settings_dependency,
)
from app.backend.repositories.device_repository import DeviceConflictError
from app.backend.schemas.device import (
    DevicePatch,
    DeviceRecord,
    DevicesListResponse,
    PortConstraints,
)
from app.backend.schemas.errors import error_detail
from app.backend.schemas.serial import SerialFlashAccepted, SerialFlashRequest
from app.backend.security import require_bearer_token
from app.backend.services.device_registry import DeviceRegistry, IncompleteConfigurationError
from app.backend.services.eeprom import EepromService
from app.backend.services.port_allocator import PortAllocatorService

router = APIRouter(
    prefix="/devices", tags=["devices"], dependencies=[Depends(require_bearer_token)]
)

_logger = logging.getLogger(__name__)

DEVICE_ID_PATH = Path(
    description='Either "serial:<value>" or "usb:<topology_path>"',
    examples=["serial:ADSB-01"],
)

# A device may only be flashed while it is not mid-lifecycle (architecture §7.6
# guard 4): streaming/starting devices refuse with 409 device_busy so a live
# feed is never silently interrupted by this endpoint.
_IDLE_STATES = frozenset({"detected", "configured", "stopped"})

_port_allocation_lock = asyncio.Lock()
"""Serializes every `PATCH` that touches `output_port` across the whole process.

`PortAllocatorService.validate()` (a read) and `DeviceRegistry.apply_patch`'s
`upsert()` (the write) run in separate transactions/round-trips, so two
concurrent `PATCH`es proposing adjacent-but-not-identical ports — device A to
1234, device B to 1236 (A's control port) — could each `validate()` before
either commits and both pass: `ux_sdr_devices_port` only indexes
`output_port`, so it cannot catch a P/P+2 *adjacency* collision, only an
identical `output_port`. Sentry is architected as a single process (ADR-0001:
one container, one supervised process tree), so a single in-process lock
around validate-then-apply is a complete fix here, not merely a mitigation —
there is no second process/replica that could still race around it.
"""


_background_flash_tasks: set[asyncio.Task[None]] = set()
"""Holds every in-flight `EepromService.flash_serial()` background task.

`asyncio.create_task()`'s return value must be kept referenced somewhere for
the lifetime of the task — otherwise it is only weakly held by the event
loop and can be garbage-collected mid-flight, silently abandoning the flash
(https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task).
Each task removes itself via `add_done_callback` once it completes."""


def _on_flash_task_done(device_id: str, operation_id: str, task: asyncio.Task[None]) -> None:
    """Untrack a finished flash task and surface any exception it raised.

    `flash_serial()` is expected to report every outcome itself via an SSE
    `notice` and never raise, but this is the last line of defence against a
    genuine bug in that path leaving the operator with no signal at all
    beyond a `202` that never resolves.
    """
    _background_flash_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        _logger.exception(
            "serial flash task for %s (operation_id=%s) raised unexpectedly",
            device_id,
            operation_id,
            exc_info=error,
        )


def _port_constraints(records: Sequence[DeviceRecord], settings: Settings) -> PortConstraints:
    """Mirror the port-allocator's rule table so the UI can validate inline (architecture §7.4).

    Advisory only: the server always re-validates the actual `PATCH` through
    `PortAllocatorService`, never trusting this summary as authoritative.
    """
    reserved = sorted({settings.http_port} | settings.reserved_port_numbers())
    ports_in_use: set[int] = set()
    for record in records:
        if record.output_port is not None:
            ports_in_use.add(record.output_port)
        if record.control_port is not None:
            ports_in_use.add(record.control_port)
    return PortConstraints(
        port_min=1024,
        port_max=65533,
        reserved=tuple(reserved),
        internal_range=(
            settings.internal_port_base,
            settings.internal_port_base + settings.max_devices,
        ),
        in_use=tuple(sorted(ports_in_use)),
    )


@router.get(
    "",
    response_model=DevicesListResponse,
    status_code=status.HTTP_200_OK,
    summary="List configured and detected devices",
)
async def list_devices(
    device_registry: DeviceRegistry = Depends(get_device_registry),
    port_allocator: PortAllocatorService = Depends(get_port_allocator),
    settings: Settings = Depends(get_settings_dependency),
) -> DevicesListResponse:
    """Return every configured device plus every detected-but-unconfigured one."""
    records = device_registry.list_records()
    return DevicesListResponse(
        devices=tuple(records),
        port_suggestion=await port_allocator.suggest_next(),
        constraints=_port_constraints(records, settings),
    )


@router.patch(
    "/{device_id}",
    response_model=DeviceRecord,
    status_code=status.HTTP_200_OK,
    summary="Create or update a device's configuration",
)
async def patch_device(
    patch: DevicePatch,
    device_id: str = DEVICE_ID_PATH,
    device_registry: DeviceRegistry = Depends(get_device_registry),
    port_allocator: PortAllocatorService = Depends(get_port_allocator),
) -> DeviceRecord:
    """Upsert one device's configuration; creates the row on first call for a detected device.

    Validation order mirrors architecture §7.5's response list: the device
    must be known and identified before any conflict is checked, the proposed
    port is validated through the full six-rule `PortAllocatorService`
    (returning its specific rejection code, not a generic one), then the name
    is checked for a case-insensitive collision, and only then is the mutation
    applied. When `output_port` is set, the whole validate-then-apply sequence
    runs under `_port_allocation_lock` — the sole guard against a P/P+2
    *adjacency* race between two concurrent requests (see that lock's
    docstring); `DeviceConflictError` from the repository's unique index is
    still caught separately as a defence against an *identical*-port race,
    which the lock also happens to prevent but which existed as a fallback
    before the lock did.
    """
    current_status = device_registry.get_status(device_id)
    if current_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("unknown_device", f"No known device {device_id!r}."),
        )
    if current_status.needs_identification:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                "device_unidentified",
                "This device has not been identified; flash it a unique serial first.",
            ),
        )

    if patch.output_port is not None:
        await _port_allocation_lock.acquire()
    try:
        if patch.output_port is not None:
            validation = await port_allocator.validate(
                patch.output_port, requesting_device_id=device_id
            )
            if not validation.is_valid:
                assert validation.rejection_code is not None  # invariant of is_valid=False
                context: dict[str, object] = {"port": patch.output_port}
                if validation.conflicts_with is not None:
                    context["conflicts_with"] = validation.conflicts_with
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=error_detail(
                        validation.rejection_code,
                        f"output_port {patch.output_port} is not assignable.",
                        **context,
                    ),
                )
        return await _apply_device_patch(patch, device_id, device_registry)
    finally:
        if patch.output_port is not None:
            _port_allocation_lock.release()


async def _apply_device_patch(
    patch: DevicePatch, device_id: str, device_registry: DeviceRegistry
) -> DeviceRecord:
    """The name-collision check and mutation tail of `patch_device`, factored out.

    Still runs under `_port_allocation_lock` whenever `patch.output_port` is
    set (the caller holds it) — kept as one function rather than inlined so
    the lock's `try`/`finally` in `patch_device` stays readable.
    """
    if patch.name is not None:
        normalized_name = patch.name.strip().lower()
        for other_record in device_registry.list_records():
            if other_record.device_id == device_id:
                continue
            if other_record.name.strip().lower() == normalized_name:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=error_detail(
                        "name_conflict",
                        f"The name {patch.name!r} is already in use.",
                        conflicts_with=other_record.device_id,
                    ),
                )

    try:
        return await device_registry.apply_patch(device_id, patch.model_dump(exclude_unset=True))
    except IncompleteConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                "incomplete_configuration",
                f"A device's first configuration must include: {', '.join(error.missing_fields)}.",
                missing_fields=list(error.missing_fields),
            ),
        ) from error
    except DeviceConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "port_conflict",
                "The requested configuration conflicts with another device.",
            ),
        ) from error


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a device's persisted configuration",
)
async def delete_device(
    device_id: str = DEVICE_ID_PATH,
    device_registry: DeviceRegistry = Depends(get_device_registry),
) -> None:
    """Remove a device's persisted configuration.

    Config-removal only, and only for a device that is not currently present
    (settled contract, see module docstring): `404 unknown_device` for a
    device_id with no persisted row, `409 device_present` while it is plugged
    in, `204 No Content` otherwise.
    """
    current_status = device_registry.get_status(device_id)
    if current_status is None or current_status.record_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("unknown_device", f"No persisted configuration for {device_id!r}."),
        )
    if current_status.present:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "device_present",
                "A present device's configuration cannot be removed; unplug it first.",
            ),
        )
    await device_registry.delete(device_id)
    return None


@router.post(
    "/{device_id}/serial",
    response_model=SerialFlashAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Flash a unique serial to the dongle's EEPROM",
)
async def flash_serial(
    request: SerialFlashRequest,
    device_id: str = DEVICE_ID_PATH,
    device_registry: DeviceRegistry = Depends(get_device_registry),
    eeprom_service: EepromService = Depends(get_eeprom_service),
) -> SerialFlashAccepted:
    """Begin the guarded EEPROM serial-flash flow; the outcome arrives via SSE `notice`.

    `request.confirm`'s `Literal[True]` and `request.serial`'s allow-list
    pattern are already enforced by Pydantic before this handler runs
    (architecture §7.6 guards 1-2). This handler enforces guards 3-4 (serial
    uniqueness, device idleness), then **synchronously** reserves the
    per-device/per-serial lock via `EepromService.begin_flash()` before
    dispatching — a separate `is_locked()` check followed by `create_task()`
    is not atomic (two concurrent requests could both observe "not locked"),
    so the reservation itself must happen inline in this handler, not inside
    the task it starts. The actual guarded flash (charset re-check, pair
    stop, list-argv exec) runs in `EepromService.flash_serial()` as a
    background task — the endpoint itself never performs the flash inline,
    matching the `202` contract.
    """
    current_status = device_registry.get_status(device_id)
    if current_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("unknown_device", f"No known device {device_id!r}."),
        )
    if current_status.state not in _IDLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "device_busy",
                f"Device is currently {current_status.state}; disable it before flashing.",
            ),
        )

    for other_record in device_registry.list_records():
        if other_record.device_id == device_id:
            continue
        if request.serial in (other_record.identity_key, other_record.last_serial):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "serial_in_use", f"Serial {request.serial!r} is already in use."
                ),
            )

    reservation_failure = eeprom_service.begin_flash(device_id, request.serial)
    if reservation_failure is not None:
        message = (
            "A serial flash is already in progress for this device."
            if reservation_failure == "device_busy"
            else f"Serial {request.serial!r} is already being flashed to another device."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(reservation_failure, message),
        )

    operation_id = str(uuid.uuid4())
    flash_task = asyncio.create_task(
        eeprom_service.flash_serial(device_id, request.serial, operation_id),
        name=f"eeprom-flash-{device_id}",
    )
    _background_flash_tasks.add(flash_task)
    flash_task.add_done_callback(lambda task: _on_flash_task_done(device_id, operation_id, task))
    return SerialFlashAccepted(
        device_id=device_id,
        operation_id=operation_id,
        status="in_progress",
        requires_replug=True,
    )
