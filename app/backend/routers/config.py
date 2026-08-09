"""`/api/config` — export and import a whole instance's configuration.

Standing up a second Pi otherwise means retyping every device's name, port,
antenna and visibility by hand and getting them all right. Export from a working
Sentry, import into a fresh one, done.

Device entries are replayed through `devices.apply_device_configuration`, the
same path `PATCH /api/devices/{id}` uses, so an imported port goes through the
identical six-rule allocation check. An import can never write a configuration
the normal endpoint would have refused.

The hotspot passphrase is importable but never exportable, so a provisioning
file an operator wrote can carry one while a file Sentry produced cannot. The
deploy-time gates (`SENTRY_HOTSPOT_CONTROL_ENABLED`, `SENTRY_AUTH_TOKEN`) are
neither — see `schemas/config.py` for why that line falls where it does.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.backend.config import Settings
from app.backend.dependencies import (
    get_clock,
    get_console_auth_service,
    get_device_registry,
    get_hotspot_service,
    get_port_allocator,
    get_settings_dependency,
)
from app.backend.example_fixtures import SENTRY_VERSION
from app.backend.interfaces.clock import Clock
from app.backend.routers.devices import apply_device_configuration
from app.backend.schemas.config import (
    CONFIG_VERSION,
    ConfigImportRequest,
    ConfigImportResult,
    DeviceConfigEntry,
    DeviceImportOutcome,
    HotspotConfigEntry,
    SentryConfig,
)
from app.backend.schemas.device import DevicePatch
from app.backend.schemas.errors import error_detail
from app.backend.security import require_console_session
from app.backend.services.console_auth import ConsoleAuthService
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.hotspot import HotspotError, HotspotService
from app.backend.services.port_allocator import PortAllocatorService

router = APIRouter(
    prefix="/config", tags=["config"], dependencies=[Depends(require_console_session)]
)

_logger = logging.getLogger(__name__)

EXPORT_FILENAME = "sentry-config.json"


async def _build_export(
    device_registry: DeviceRegistry,
    hotspot_service: HotspotService,
    clock: Clock,
) -> SentryConfig:
    """Assemble this instance's exportable configuration.

    Only *configured* devices are exported. A merely-detected dongle has no
    operator-set configuration to carry, and writing one out would produce
    entries that say nothing.
    """
    devices = tuple(
        DeviceConfigEntry(
            identity_kind=record.identity_kind,
            identity_key=record.identity_key,
            name=record.name,
            description=record.description,
            notes=record.notes,
            antenna=record.antenna,
            output_port=record.output_port,
            enabled=record.enabled,
            visibility=record.visibility,
            center_hz=record.center_hz,
            sample_rate=record.sample_rate,
            gain_db=record.gain_db,
            gain_auto=record.gain_auto,
            ppm_correction=record.ppm_correction,
            bias_tee=record.bias_tee,
            direct_sampling=record.direct_sampling,
        )
        for record in device_registry.list_records()
        if record.record_id is not None
    )

    snapshot = await hotspot_service.get_snapshot()
    state = snapshot.state
    hotspot = (
        HotspotConfigEntry(
            ssid=state.ssid,
            hidden=state.hidden,
            security=state.security,
            band=state.band,
            channel=state.channel,
            gateway_cidr=state.gateway_cidr,
            interface=state.interface,
            enabled=state.autoconnect,
            # A flag, never the key. There is no code path in this module that
            # could put a passphrase into an exported file.
            passphrase_set=state.passphrase_set,
        )
        if state.profile_exists
        else None
    )

    return SentryConfig(
        version=CONFIG_VERSION,
        generated_at=clock.now_ms(),
        sentry_version=SENTRY_VERSION,
        devices=devices,
        hotspot=hotspot,
    )


@router.get(
    "",
    response_model=SentryConfig,
    status_code=status.HTTP_200_OK,
    summary="Export this instance's configuration",
)
async def export_config(
    device_registry: DeviceRegistry = Depends(get_device_registry),
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    clock: Clock = Depends(get_clock),
) -> SentryConfig:
    """Return the whole configuration as JSON, for import into another Sentry."""
    return await _build_export(device_registry, hotspot_service, clock)


@router.get(
    "/download",
    status_code=status.HTTP_200_OK,
    summary="Export the configuration as a downloadable file",
    response_class=Response,
)
async def download_config(
    device_registry: DeviceRegistry = Depends(get_device_registry),
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    clock: Clock = Depends(get_clock),
) -> Response:
    """The same payload as `GET /api/config`, with a filename attached.

    For `curl -O` and scripted backups. The web UI deliberately does *not* use
    this route: a plain navigation cannot set an `Authorization` header, so
    linking at it would 401 as soon as an operator sets a token, and the usual
    workaround — putting the token in the query string, as `EventSource` is
    forced to — would write a credential into browser history and the access
    log. The UI fetches `GET /api/config` authenticated and saves the file
    itself instead.
    """
    config = await _build_export(device_registry, hotspot_service, clock)
    payload = json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False)
    return Response(
        content=payload + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{EXPORT_FILENAME}"'},
    )


def _patch_from_entry(entry: DeviceConfigEntry) -> DevicePatch:
    """Map one exported entry onto the patch body the device endpoint accepts."""
    return DevicePatch(
        name=entry.name,
        description=entry.description,
        notes=entry.notes,
        antenna=entry.antenna,
        output_port=entry.output_port,
        enabled=entry.enabled,
        visibility=entry.visibility,
        center_hz=entry.center_hz,
        sample_rate=entry.sample_rate,
        gain_db=entry.gain_db,
        gain_auto=entry.gain_auto,
        ppm_correction=entry.ppm_correction,
        bias_tee=entry.bias_tee,
        direct_sampling=entry.direct_sampling,
    )


async def _import_devices(
    entries: tuple[DeviceConfigEntry, ...],
    device_registry: DeviceRegistry,
    port_allocator: PortAllocatorService,
) -> list[DeviceImportOutcome]:
    """Apply each device entry, reporting per entry rather than failing the batch.

    A partial import is the *expected* outcome, not an error: the destination Pi
    may not have every dongle plugged in yet, and one whose port is already
    taken should not stop the other five from landing. Each entry's fate is
    reported so an operator can see exactly what happened rather than inferring
    it from the device list afterwards.
    """
    outcomes: list[DeviceImportOutcome] = []
    for entry in entries:
        device_id = f"{entry.identity_kind}:{entry.identity_key}"
        try:
            await apply_device_configuration(
                _patch_from_entry(entry), device_id, device_registry, port_allocator
            )
        except HTTPException as error:
            detail = error.detail
            code = detail.get("code", "") if isinstance(detail, dict) else ""
            message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
            # A device the file knows about but this Pi has never seen is the
            # ordinary "not plugged in here yet" case, not a failure.
            outcome: Literal["applied", "skipped", "failed"] = (
                "skipped" if code == "unknown_device" else "failed"
            )
            if outcome == "skipped":
                message = "Not detected on this Sentry — plug the dongle in and import again."
            outcomes.append(
                DeviceImportOutcome(
                    identity_kind=entry.identity_kind,
                    identity_key=entry.identity_key,
                    outcome=outcome,
                    detail=str(message),
                )
            )
            continue
        outcomes.append(
            DeviceImportOutcome(
                identity_kind=entry.identity_kind,
                identity_key=entry.identity_key,
                outcome="applied",
            )
        )
    return outcomes


async def _import_hotspot(
    entry: HotspotConfigEntry,
    hotspot_service: HotspotService,
    settings: Settings,
    password_set: bool,
) -> tuple[bool, str]:
    """Apply the file's hotspot settings, returning `(applied, why_not)`.

    Never starts the hotspot, even when the file sets a password and could.
    A file import should not put a network on the air — an operator turns it on
    deliberately, from a UI that shows them what they are about to broadcast.
    The settings are written and nothing is activated.

    A file may carry a passphrase (`HotspotConfigEntry.passphrase`, inbound
    only), which is what lets a fresh Pi be provisioned to a working hotspot in
    one import. Without one the old precondition still holds: a destination with
    no stored password has nothing to raise the network with later, so writing
    an SSID it can never use would be a silent half-success.
    """
    if not settings.hotspot_control_enabled:
        return False, "Hotspot control is switched off on this Sentry."
    if entry.ssid is None:
        return False, "The file has no hotspot network name."

    file_passphrase = entry.passphrase.get_secret_value() if entry.passphrase else None

    # Same gate as every other hotspot mutation (`routers/hotspot.py`), applied
    # here too because a file that sets a password is one, and an import must
    # not be a way around it.
    if file_passphrase is not None and settings.hotspot_require_auth_token and not password_set:
        return False, (
            "Set a console password before importing a hotspot password: anyone who joins "
            "the network can otherwise reach this API without signing in."
        )

    if file_passphrase is None:
        snapshot = await hotspot_service.get_snapshot()
        if not snapshot.state.passphrase_set:
            return False, (
                "No hotspot password is set on this Sentry, and this file does not carry one. "
                "Set a password in the hotspot panel first, or add a `passphrase` to the "
                "file's hotspot section."
            )

    try:
        await hotspot_service.apply_configuration(
            ssid=entry.ssid,
            # `None` leaves whatever is already stored alone, which is what an
            # export-shaped file (no passphrase key) should do.
            passphrase=file_passphrase,
            security=entry.security,
            hidden=entry.hidden,
            enabled=False,
            interface=entry.interface,
            band=entry.band,
            channel=entry.channel,
            gateway_cidr=entry.gateway_cidr,
            confirm_uplink_loss=False,
        )
    except HotspotError as error:
        return False, error.message
    return True, ""


@router.post(
    "",
    response_model=ConfigImportResult,
    status_code=status.HTTP_200_OK,
    summary="Import a configuration exported from another Sentry",
)
async def import_config(
    request_body: ConfigImportRequest,
    device_registry: DeviceRegistry = Depends(get_device_registry),
    port_allocator: PortAllocatorService = Depends(get_port_allocator),
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    clock: Clock = Depends(get_clock),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
) -> ConfigImportResult:
    """Apply an exported configuration, reporting what landed and what did not."""
    config = request_body.config
    if config.version != CONFIG_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                "unsupported_config_version",
                f"This Sentry understands config version {CONFIG_VERSION}, "
                f"and the file is version {config.version}.",
                supported=CONFIG_VERSION,
                received=config.version,
            ),
        )

    outcomes: list[DeviceImportOutcome] = []
    if request_body.apply_devices:
        outcomes = await _import_devices(config.devices, device_registry, port_allocator)

    hotspot_applied = False
    hotspot_detail = ""
    if request_body.apply_hotspot:
        if config.hotspot is None:
            hotspot_detail = "The file has no hotspot configuration."
        else:
            hotspot_applied, hotspot_detail = await _import_hotspot(
                config.hotspot, hotspot_service, settings, await console_auth.is_password_set()
            )

    _logger.info(
        "config import: %d applied, %d skipped, %d failed, hotspot_applied=%s",
        sum(1 for outcome in outcomes if outcome.outcome == "applied"),
        sum(1 for outcome in outcomes if outcome.outcome == "skipped"),
        sum(1 for outcome in outcomes if outcome.outcome == "failed"),
        hotspot_applied,
    )

    return ConfigImportResult(
        devices=tuple(outcomes),
        devices_applied=sum(1 for outcome in outcomes if outcome.outcome == "applied"),
        devices_skipped=sum(1 for outcome in outcomes if outcome.outcome == "skipped"),
        devices_failed=sum(1 for outcome in outcomes if outcome.outcome == "failed"),
        hotspot_applied=hotspot_applied,
        hotspot_detail=hotspot_detail,
        generated_at=clock.now_ms(),
    )
