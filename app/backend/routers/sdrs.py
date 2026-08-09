"""`GET /api/v1/sdrs` — the versioned Sentinel contract, plus its `/api/sdrs` alias (§7.7).

This is the only surface a separately-deployed Sentinel consumes, so it is
additive-only within a major version and never changed to suit the UI.

It publishes only the devices the operator has marked **public**. A Sentry
with four dongles can therefore offer any subset of them to other Sentinel
instances, keeping the rest off the list entirely.

**This route requires no authentication** (ADR-0010). Sentinel is a read-only
consumer and holds no credential, so the `visibility` flag is the whole access
control here — which makes it heavier than it was. "Private" used to mean "not
exported to Sentinel"; it now means "not readable by anyone who can reach this
Pi". Everything published here — name, host, port, description, notes, antenna —
is readable by any client on the network.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.backend.config import Settings
from app.backend.dependencies import get_clock, get_device_registry, get_settings_dependency
from app.backend.example_fixtures import SENTRY_VERSION
from app.backend.interfaces.clock import Clock
from app.backend.routers.host_resolution import resolve_public_host
from app.backend.schemas.device import DeviceRecord
from app.backend.schemas.sdr_export import (
    SDR_EXPORT_API_VERSION,
    SdrExportItem,
    SdrExportResponse,
    SdrExportSource,
)
from app.backend.services.device_registry import DeviceRegistry

router = APIRouter(tags=["sdrs"])

API_VERSION_HEADER = "X-Sentry-Sdr-Api-Version"


def _map_to_export_item(record: DeviceRecord) -> SdrExportItem:
    """Map one `DeviceRecord` onto Sentinel's field names (architecture §7.8)."""
    description = record.description.strip()
    if not description:
        description = (
            f"{record.identity_kind}:{record.identity_key} @ USB {record.last_topology_path}"
        )
    return SdrExportItem(
        sentry_device_id=record.device_id,
        name=record.name,
        host="",  # overwritten by the caller, which knows the request/settings
        port=record.output_port or 0,
        control_port=record.control_port or 0,
        description=description,
        notes=record.notes,
        antenna=record.antenna,
        enabled=record.enabled,
        bandwidth=record.sample_rate,
        rf_gain=None if record.gain_auto else record.gain_db,
        agc=record.gain_auto,
        available=record.present,
        state=record.state,
    )


async def _build_sdr_export(
    request: Request,
    response: Response,
    device_registry: DeviceRegistry,
    settings: Settings,
    clock: Clock,
    include_disabled: bool,
    available_only: bool,
) -> SdrExportResponse:
    """Shared body for both `/api/v1/sdrs` and its `/api/sdrs` alias.

    Only devices with a persisted row (`record_id is not None`, i.e.
    *configured*) are exported — a merely-detected dongle is not yet part of
    Sentinel's radio list (architecture §7.7).

    **Private devices are omitted entirely**, not merely flagged. Sentry may
    run more dongles than its operator wants to share, so each device carries
    a `visibility` the operator sets per device in the UI; anything left
    `private` (the default) never reaches this list, in any query-parameter
    combination. There is deliberately no `include_private` escape hatch —
    the export is the one surface an arbitrary Sentinel consumes, so a
    parameter that could reveal a withheld device's IQ endpoint would defeat
    the point of the toggle.
    """
    response.headers[API_VERSION_HEADER] = str(SDR_EXPORT_API_VERSION)
    host = resolve_public_host(request, settings)

    items: list[SdrExportItem] = []
    for record in device_registry.list_records():
        if record.record_id is None:
            continue
        if record.visibility != "public":
            continue
        if not include_disabled and not record.enabled:
            continue
        if available_only and not record.present:
            continue
        item = _map_to_export_item(record)
        items.append(item.model_copy(update={"host": host}))

    return SdrExportResponse(
        api_version=SDR_EXPORT_API_VERSION,
        generated_at=clock.now_ms(),
        source=SdrExportSource(version=SENTRY_VERSION, host=host, http_port=settings.http_port),
        control_port_offset=2,
        sdrs=tuple(items),
    )


@router.get(
    "/v1/sdrs",
    response_model=SdrExportResponse,
    status_code=status.HTTP_200_OK,
    summary="The Sentinel-consumed export of public SDRs (versioned)",
)
async def get_sdrs_v1(
    response: Response,
    request: Request,
    include_disabled: bool = Query(default=False),
    available_only: bool = Query(default=False),
    device_registry: DeviceRegistry = Depends(get_device_registry),
    settings: Settings = Depends(get_settings_dependency),
    clock: Clock = Depends(get_clock),
) -> SdrExportResponse:
    """Return every *public* configured device, mapped onto Sentinel's `SdrRadio` field names.

    Devices left `private` are omitted from `sdrs` entirely — see
    `_build_sdr_export`.
    """
    return await _build_sdr_export(
        request, response, device_registry, settings, clock, include_disabled, available_only
    )


@router.get(
    "/sdrs",
    response_model=SdrExportResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanent alias for the current stable /v1/sdrs",
)
async def get_sdrs_alias(
    response: Response,
    request: Request,
    include_disabled: bool = Query(default=False),
    available_only: bool = Query(default=False),
    device_registry: DeviceRegistry = Depends(get_device_registry),
    settings: Settings = Depends(get_settings_dependency),
    clock: Clock = Depends(get_clock),
) -> SdrExportResponse:
    """Permanent convenience alias serving the current stable SDR export version."""
    return await _build_sdr_export(
        request, response, device_registry, settings, clock, include_disabled, available_only
    )
