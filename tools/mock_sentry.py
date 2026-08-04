#!/usr/bin/env python3
"""Mock Sentry server for frontend development — no hardware, no real backend.

Serves the frozen API contract (architecture §7) with scripted fixture data,
including a plug/unplug sequence over SSE, so the frontend track (1C) can
build the live-update UI against real, schema-valid traffic before any
adapter, service or router is implemented for real.

Run with:  uv run uvicorn tools.mock_sentry:app --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.backend.schemas.device import (
    ClientCounts,
    DevicePatch,
    DeviceRecord,
    DevicesListResponse,
    DeviceStatus,
    OutputInfo,
    PortConstraints,
    ProcessInfo,
    StatusResponse,
    TunerInfo,
    UsbInfo,
    UsbLastKnownInfo,
)
from app.backend.schemas.errors import error_detail
from app.backend.schemas.events import DeviceRemovedEvent, NoticeItem
from app.backend.schemas.health import DeviceCounts, HealthResponse, HotplugHealth
from app.backend.schemas.hotspot import (
    HotspotActivationRequest,
    HotspotClientItem,
    HotspotClientsResponse,
    HotspotConfigRequest,
    HotspotStateResponse,
    HotspotWarning,
    WirelessInterfaceItem,
    WirelessInterfacesResponse,
)
from app.backend.schemas.sdr_export import (
    SDR_EXPORT_API_VERSION,
    SdrExportItem,
    SdrExportResponse,
    SdrExportSource,
)
from app.backend.schemas.serial import SerialFlashAccepted, SerialFlashRequest

# Idle states the guarded serial-flash flow may run from (mirrors
# `app/backend/routers/devices.py`'s `_IDLE_STATES` — architecture §7.6 guard 4).
_MOCK_IDLE_STATES = frozenset({"detected", "configured", "stopped"})

MOCK_VERSION = "0.1.0-mock"
STARTED_AT_MS = int(time.time() * 1000)
API_VERSION_HEADER = "X-Sentry-Sdr-Api-Version"

# ── Fixture set: two dongles. One is stable and streaming throughout; the
#    other cycles detected → configuring → streaming → unplugged → replugged
#    so the frontend's hotplug/live-update paths have something to render.

_STABLE_USB = UsbInfo(
    topology_path="1-1.2",
    bus_number=1,
    port_chain=(1, 2),
    hub_depth=1,
    device_address=4,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="Realtek",
    product="RTL2838UHIDIR",
    serial="AIS-01",
    driver="rtl2832u",
    driver_conflict=False,
)

_STABLE_DEVICE = DeviceStatus(
    device_id="serial:AIS-01",
    record_id=1,
    identity_kind="serial",
    identity_key="AIS-01",
    needs_identification=False,
    name="AIS SDR",
    description="Roof, 162 MHz",
    notes="Feeder cable due for replacement — intermittent below 150 MHz.",
    antenna="Discone, roof mast",
    visibility="public",
    state="streaming",
    state_since=STARTED_AT_MS,
    state_reason=None,
    present=True,
    enabled=True,
    usb=_STABLE_USB,
    output=OutputInfo(host="192.168.1.45", iq_port=1234, control_port=1236),
    tuner=TunerInfo(
        center_hz=162_000_000,
        sample_rate=2_048_000,
        gain_db=30.0,
        gain_auto=True,
        locked=False,
        observed_at=STARTED_AT_MS,
        bias_tee=None,
        direct_sampling=None,
    ),
    processes=ProcessInfo(
        rtl_tcp_pid=901,
        relay_pid=902,
        internal_port=14000,
        restarts=0,
        last_restart_at=None,
        last_exit_code=None,
    ),
    clients=ClientCounts(iq=1, control=0),
    last_seen_at=STARTED_AT_MS,
)

# A pair of tier-3 devices (architecture §5.1): both report the factory-default
# `00000001` serial, so neither can be trusted as a persistence key until the
# operator flashes a unique one. Exercises `NeedsIdentificationNotice`,
# `SerialConflictBanner` and `SerialFlashDialog`, none of which the fixture
# fixture set previously reached.
_CONFLICT_USB_A = UsbInfo(
    topology_path="1-3.1",
    bus_number=1,
    port_chain=(1, 3, 1),
    hub_depth=1,
    device_address=9,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="Realtek",
    product="RTL2838UHIDIR",
    serial="00000001",
    driver="rtl2832u",
    driver_conflict=False,
)

_CONFLICT_DEVICE_A = DeviceStatus(
    device_id="usb:1-3.1",
    record_id=None,
    identity_kind="usb",
    identity_key="1-3.1",
    needs_identification=True,
    name="",
    description="",
    state="detected",
    state_since=STARTED_AT_MS,
    state_reason=None,
    present=True,
    enabled=False,
    usb=_CONFLICT_USB_A,
    output=None,
    tuner=None,
    processes=None,
    clients=None,
    last_seen_at=STARTED_AT_MS,
)

_CONFLICT_DEVICE_B = _CONFLICT_DEVICE_A.model_copy(
    update={
        "device_id": "usb:1-3.2",
        "identity_key": "1-3.2",
        "usb": _CONFLICT_USB_A.model_copy(
            update={"topology_path": "1-3.2", "port_chain": (1, 3, 2)}
        ),
    }
)

# Reproduces the exact "three cards for two dongles" scenario a real Pi with a
# flaky USB hub produces (see the forget/delete feature's design brief): a
# topology-keyed identity means a re-enumerated dongle becomes a brand-new
# absent record rather than reattaching to its old one. Two configured
# devices are absent ("ghosts") and one detected device is present but never
# configured — exercising `AbsentDeviceGroup`, `DeviceIdentitySummary`'s
# make/model rendering, and the forget/delete flow this mock server's new
# `DELETE /api/devices/{device_id}` route backs.
#
# `_RTLSDR_V4_USB`/`_PRESENT_RTLSDR_V4` also reproduce a real-hardware
# regression: on a live Pi, RTL-SDR-V4 was plugged into a port (present,
# configured) at the exact same moment NESDR-SMART's *last-known* path
# (`_GHOST_NESDR_SMART`, below — a separate, absent, configured device)
# pointed at that same port — the one it used to occupy before being
# swapped out. Reproduced here as "1-1.3", both devices' shared path.
# `buildTopologyTree` must place only the present device ("RTL-SDR-V4") in
# the topology tree and leave the absent one ("NESDR-SMART") out of it
# entirely, even though both devices still render as cards.
_RTLSDR_V4_USB = UsbInfo(
    topology_path="1-1.3",
    bus_number=1,
    port_chain=(1, 3),
    hub_depth=1,
    device_address=5,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="RTLSDRBlog",
    product="Blog V4",
    serial="00000001",
    driver="rtl2832u",
    driver_conflict=False,
)

_PRESENT_RTLSDR_V4 = DeviceStatus(
    device_id="usb:1-2.1",
    record_id=3,
    identity_kind="usb",
    identity_key="1-2.1",
    needs_identification=False,
    name="RTL-SDR-V4",
    description="Roof, replugged after the hub swap",
    notes="",
    antenna="1090 collinear, loft",
    visibility="private",
    state="configured",
    state_since=STARTED_AT_MS,
    state_reason=None,
    present=True,
    enabled=True,
    usb=_RTLSDR_V4_USB,
    usb_last_known=None,
    output=OutputInfo(host="192.168.1.45", iq_port=1250, control_port=1252),
    tuner=None,
    processes=None,
    clients=None,
    last_seen_at=STARTED_AT_MS,
)

_PRESENT_UNCONFIGURED_USB = UsbInfo(
    topology_path="1-2.2",
    bus_number=1,
    port_chain=(1, 2, 2),
    hub_depth=1,
    device_address=11,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="Nooelec",
    product="NESDR SMArt v5",
    serial=None,
    driver="rtl2832u",
    driver_conflict=False,
)

_PRESENT_UNCONFIGURED_DEVICE = DeviceStatus(
    device_id="usb:1-2.2",
    record_id=None,
    identity_kind="usb",
    identity_key="1-2.2",
    needs_identification=False,
    name="",
    description="",
    state="detected",
    state_since=STARTED_AT_MS,
    state_reason=None,
    present=True,
    enabled=False,
    usb=_PRESENT_UNCONFIGURED_USB,
    output=None,
    tuner=None,
    processes=None,
    clients=None,
    last_seen_at=STARTED_AT_MS,
)

_GHOST_NESDR_SMART = DeviceStatus(
    device_id="usb:1-2.3",
    record_id=4,
    identity_kind="usb",
    identity_key="1-2.3",
    needs_identification=False,
    name="NESDR-SMART",
    # Its last-known path, "1-1.3", is the same path RTL-SDR-V4 currently
    # occupies (`_PRESENT_RTLSDR_V4`, above) — the real-hardware collision
    # `buildTopologyTree` must resolve by placing only the present device.
    description="Was port 1-1.3, now occupied by a different dongle",
    state="stopped",
    state_since=STARTED_AT_MS,
    state_reason=None,
    present=False,
    enabled=True,
    usb=None,
    usb_last_known=UsbLastKnownInfo(
        topology_path="1-1.3",
        vendor_id="0bda",
        product_id="2838",
        manufacturer="Nooelec",
        product="NESDR SMArt v5",
        serial=None,
    ),
    output=OutputInfo(host="192.168.1.45", iq_port=1254, control_port=1256),
    tuner=None,
    processes=None,
    clients=None,
    last_seen_at=STARTED_AT_MS - 1_200_000,
)

_HOTPLUG_USB = UsbInfo(
    topology_path="1-1.4.2",
    bus_number=1,
    port_chain=(1, 4, 2),
    hub_depth=2,
    device_address=7,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="Realtek",
    product="RTL2838UHIDIR",
    serial=None,
    driver="rtl2832u",
    driver_conflict=False,
)

_HOTPLUG_DETECTED = DeviceStatus(
    device_id="usb:1-1.4.2",
    record_id=None,
    identity_kind="usb",
    identity_key="1-1.4.2",
    needs_identification=False,
    name="",
    description="",
    state="detected",
    state_since=STARTED_AT_MS,
    state_reason=None,
    present=True,
    enabled=False,
    usb=_HOTPLUG_USB,
    output=None,
    tuner=None,
    processes=None,
    clients=None,
    last_seen_at=STARTED_AT_MS,
)

# The scripted timeline: (delay_seconds_before_this_step, updated hotplug device or None-to-remove).
_HOTPLUG_STARTING = _HOTPLUG_DETECTED.model_copy(
    update={
        "device_id": "serial:ADSB-02",
        "record_id": 2,
        "identity_kind": "serial",
        "identity_key": "ADSB-02",
        "name": "ADSB SDR",
        "description": "Roof, 1090 MHz",
        "state": "starting",
        "enabled": True,
        "output": OutputInfo(host="192.168.1.45", iq_port=1238, control_port=1240),
    }
)

_HOTPLUG_STREAMING = _HOTPLUG_STARTING.model_copy(
    update={
        "state": "streaming",
        "tuner": TunerInfo(
            center_hz=1_090_000_000,
            sample_rate=2_400_000,
            gain_db=40.2,
            gain_auto=False,
            locked=False,
            observed_at=STARTED_AT_MS,
            bias_tee=None,
            direct_sampling=None,
        ),
        "processes": ProcessInfo(
            rtl_tcp_pid=811,
            relay_pid=812,
            internal_port=14001,
            restarts=0,
            last_restart_at=None,
            last_exit_code=None,
        ),
        "clients": ClientCounts(iq=1, control=0),
    }
)

_HOTPLUG_TIMELINE: tuple[tuple[float, DeviceStatus | None], ...] = (
    (0.0, _HOTPLUG_DETECTED),
    (4.0, _HOTPLUG_STARTING),
    (3.0, _HOTPLUG_STREAMING),
    (6.0, None),  # unplugged
)


class MockSdrsState:
    """The mock server's mutable in-memory SDR set — a dev convenience, not production code."""

    def __init__(self) -> None:
        self.devices: dict[str, DeviceStatus] = {
            "serial:AIS-01": _STABLE_DEVICE,
            "usb:1-3.1": _CONFLICT_DEVICE_A,
            "usb:1-3.2": _CONFLICT_DEVICE_B,
            "usb:1-2.1": _PRESENT_RTLSDR_V4,
            "usb:1-2.2": _PRESENT_UNCONFIGURED_DEVICE,
            "usb:1-2.3": _GHOST_NESDR_SMART,
        }

    def status_response(self) -> StatusResponse:
        """Assemble the current `GET /api/status` / SSE `snapshot` body."""
        ordered = sorted(
            self.devices.values(),
            key=lambda device: (device.usb is None, device.usb.topology_path if device.usb else ""),
        )
        return StatusResponse(generated_at=int(time.time() * 1000), sdrs=tuple(ordered))

    def health_response(self) -> HealthResponse:
        """Assemble the current `GET /api/health` body."""
        states = [device.state for device in self.devices.values()]
        return HealthResponse(
            status="ok",
            version=MOCK_VERSION,
            started_at=STARTED_AT_MS,
            uptime_s=(time.time() * 1000 - STARTED_AT_MS) / 1000.0,
            database="ok",
            hotplug=HotplugHealth(
                source="udev", healthy=True, last_event_at=int(time.time() * 1000)
            ),
            devices=DeviceCounts(
                present=sum(1 for device in self.devices.values() if device.present),
                configured=sum(
                    1 for device in self.devices.values() if device.record_id is not None
                ),
                streaming=states.count("streaming"),
                degraded=states.count("degraded"),
                error=states.count("error"),
                needs_identification=sum(
                    1 for device in self.devices.values() if device.needs_identification
                ),
            ),
        )


_sdrs_state = MockSdrsState()
_subscriber_queues: set[asyncio.Queue[str]] = set()


def _broadcast(event_name: str, payload: object) -> None:
    """Push one formatted SSE frame to every currently-connected mock subscriber."""
    frame = f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
    for queue in _subscriber_queues:
        queue.put_nowait(frame)


async def _run_hotplug_script() -> None:
    """Replay `_HOTPLUG_TIMELINE` forever, broadcasting `device_changed`/`device_removed`."""
    while True:
        for delay_s, device in _HOTPLUG_TIMELINE:
            await asyncio.sleep(delay_s)
            if device is None:
                removed_id = "serial:ADSB-02"
                _sdrs_state.devices.pop(removed_id, None)
                _broadcast(
                    "device_removed",
                    json.loads(
                        DeviceRemovedEvent(device_id=removed_id, record_id=2).model_dump_json()
                    ),
                )
            else:
                _sdrs_state.devices[device.device_id] = device
                _broadcast("device_changed", json.loads(device.model_dump_json()))
        _broadcast(
            "notice",
            json.loads(
                NoticeItem(
                    level="info",
                    code="script_looped",
                    message="Mock hotplug sequence looped back to the start.",
                    device_id=None,
                    ts=int(time.time() * 1000),
                ).model_dump_json()
            ),
        )


async def _run_health_heartbeat() -> None:
    """Broadcast `health` every 5s, doubling as the SSE keepalive (architecture §7.3)."""
    while True:
        await asyncio.sleep(5.0)
        _broadcast("health", json.loads(_sdrs_state.health_response().model_dump_json()))


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the background scripted-event tasks for the process lifetime."""
    hotplug_task = asyncio.create_task(_run_hotplug_script())
    heartbeat_task = asyncio.create_task(_run_health_heartbeat())
    try:
        yield
    finally:
        hotplug_task.cancel()
        heartbeat_task.cancel()


app = FastAPI(title="Sentry (mock)", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def mock_health() -> HealthResponse:
    """Serve the current mock health snapshot."""
    return _sdrs_state.health_response()


@app.get("/api/status", response_model=StatusResponse)
async def mock_status() -> StatusResponse:
    """Serve the current mock realtime status."""
    return _sdrs_state.status_response()


@app.get("/api/devices", response_model=DevicesListResponse)
async def mock_list_devices() -> DevicesListResponse:
    """Serve a configuration-centric device list derived from the mock SDR set."""
    records = tuple(
        DeviceRecord(
            device_id=device.device_id,
            record_id=device.record_id,
            identity_kind=device.identity_kind,
            identity_key=device.identity_key,
            name=device.name,
            description=device.description,
            notes=device.notes,
            antenna=device.antenna,
            output_port=device.output.iq_port if device.output else None,
            control_port=device.output.control_port if device.output else None,
            enabled=device.enabled,
            visibility=device.visibility,
            center_hz=device.tuner.center_hz if device.tuner else None,
            sample_rate=device.tuner.sample_rate if device.tuner else None,
            gain_db=device.tuner.gain_db if device.tuner else None,
            gain_auto=device.tuner.gain_auto if device.tuner else True,
            ppm_correction=0,
            bias_tee=None,
            direct_sampling=None,
            present=device.present,
            needs_identification=device.needs_identification,
            state=device.state,
            last_topology_path=device.usb.topology_path if device.usb else "",
            last_serial=device.usb.serial or "" if device.usb else "",
            last_seen_at=device.last_seen_at,
            created_at=STARTED_AT_MS,
            updated_at=STARTED_AT_MS,
        )
        for device in _sdrs_state.devices.values()
    )
    return DevicesListResponse(
        devices=records,
        port_suggestion=1242,
        constraints=PortConstraints(
            port_min=1024,
            port_max=65533,
            reserved=(8000,),
            internal_range=(14000, 14008),
            in_use=tuple(
                port
                for device in _sdrs_state.devices.values()
                if device.output
                for port in (device.output.iq_port, device.output.control_port)
            ),
        ),
    )


# The `DevicePatch` fields that live directly on `DeviceStatus` under the same
# name, so a mock PATCH can apply them to the SDRs by copying them across.
# `output_port` and the tuner fields are deliberately excluded: they land on the
# nested `output`/`tuner` objects, and the mock has never needed to model that.
_PATCHABLE_STATUS_FIELDS = ("name", "description", "notes", "antenna", "enabled", "visibility")


@app.patch("/api/devices/{device_id}", response_model=DeviceRecord)
async def mock_patch_device(device_id: str, patch: DevicePatch) -> DeviceRecord:
    """Apply an accepted PATCH to the mock SDR set, then echo back the resulting record.

    The patch is applied to `_sdrs_state` (and broadcast as `device_changed`)
    rather than only echoed, because the frontend clears a pending optimistic
    patch by comparing the *streamed* device against what it sent. Echoing
    alone left every committed edit pending until something else happened to
    republish the device, which made a toggle look like it had sprung back.
    """
    updated_fields = patch.model_dump(exclude_unset=True)
    device = _sdrs_state.devices.get(device_id)
    if device is not None:
        applied = {
            field: value
            for field, value in updated_fields.items()
            if field in _PATCHABLE_STATUS_FIELDS and value is not None
        }
        if applied:
            device = device.model_copy(update=applied)
            _sdrs_state.devices[device_id] = device
            _broadcast("device_changed", json.loads(device.model_dump_json()))

    devices_response = await mock_list_devices()
    for record in devices_response.devices:
        if record.device_id == device_id:
            return record.model_copy(update=updated_fields)
    return devices_response.devices[0]


@app.delete("/api/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def mock_delete_device(device_id: str) -> Response:
    """Mock the forget flow: `404` unknown, `409 device_present` while plugged, else `204`."""
    device = _sdrs_state.devices.get(device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("unknown_device", f"No known device {device_id!r}."),
        )
    if device.present:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "device_present", "Device is currently present; unplug it before forgetting it."
            ),
        )
    del _sdrs_state.devices[device_id]
    _broadcast(
        "device_removed",
        json.loads(
            DeviceRemovedEvent(device_id=device_id, record_id=device.record_id).model_dump_json()
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/devices/{device_id}/serial",
    response_model=SerialFlashAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def mock_flash_serial(device_id: str, request: SerialFlashRequest) -> SerialFlashAccepted:
    """Mock the guarded EEPROM flash flow: the same guards as the real endpoint (architecture
    §7.6), then a scripted 202 followed by a delayed SSE `notice` — never touches real hardware.
    """
    device = _sdrs_state.devices.get(device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("unknown_device", f"No known device {device_id!r}."),
        )
    if device.state not in _MOCK_IDLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "device_busy", f"Device is currently {device.state}; disable it before flashing."
            ),
        )
    for other_id, other_device in _sdrs_state.devices.items():
        if other_id == device_id:
            continue
        if other_device.usb is not None and other_device.usb.serial == request.serial:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "serial_in_use", f"Serial {request.serial!r} is already in use."
                ),
            )

    operation_id = str(uuid.uuid4())
    asyncio.create_task(_mock_run_flash(device_id, request.serial))
    return SerialFlashAccepted(
        device_id=device_id,
        operation_id=operation_id,
        status="in_progress",
        requires_replug=True,
    )


async def _mock_run_flash(device_id: str, serial: str) -> None:
    """Scripted flash outcome: always succeeds after a short delay, broadcast as an SSE `notice`."""
    await asyncio.sleep(2.0)
    _broadcast(
        "notice",
        json.loads(
            NoticeItem(
                level="info",
                code="serial_flash_succeeded",
                message=f"Serial {serial!r} written. Replug the device to see it.",
                device_id=device_id,
                ts=int(time.time() * 1000),
            ).model_dump_json()
        ),
    )
    device = _sdrs_state.devices.get(device_id)
    if device is not None:
        updated = device.model_copy(update={"state": "stopped", "state_reason": "awaiting_replug"})
        _sdrs_state.devices[device_id] = updated
        _broadcast("device_changed", json.loads(updated.model_dump_json()))


@app.get("/api/v1/sdrs", response_model=SdrExportResponse)
@app.get("/api/sdrs", response_model=SdrExportResponse)
async def mock_sdrs(
    response: Response,
    request: Request,
    include_disabled: bool = Query(default=False),
    available_only: bool = Query(default=False),
) -> SdrExportResponse:
    """Serve the mock Sentinel export, derived from the mock SDR set."""
    del request
    response.headers[API_VERSION_HEADER] = str(SDR_EXPORT_API_VERSION)
    items = []
    for device in _sdrs_state.devices.values():
        # Mirrors the real router: a private device is never published, in any
        # query-parameter combination.
        if device.visibility != "public":
            continue
        if not device.enabled and not include_disabled:
            continue
        if available_only and not device.present:
            continue
        if device.output is None:
            continue
        items.append(
            SdrExportItem(
                sentry_device_id=device.device_id,
                name=device.name,
                host=device.output.host,
                port=device.output.iq_port,
                control_port=device.output.control_port,
                description=device.description,
                notes=device.notes,
                antenna=device.antenna,
                enabled=device.enabled,
                bandwidth=device.tuner.sample_rate if device.tuner else None,
                rf_gain=device.tuner.gain_db
                if device.tuner and not device.tuner.gain_auto
                else None,
                agc=device.tuner.gain_auto if device.tuner else None,
                available=device.present,
                state=device.state,
            )
        )
    return SdrExportResponse(
        api_version=SDR_EXPORT_API_VERSION,
        generated_at=int(time.time() * 1000),
        source=SdrExportSource(
            name="sentry", version=MOCK_VERSION, host="192.168.1.45", http_port=8000
        ),
        control_port_offset=2,
        sdrs=tuple(items),
    )


async def _subscriber_stream() -> AsyncIterator[str]:
    """One SSE connection: the initial snapshot, then every broadcast frame."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
    _subscriber_queues.add(queue)
    try:
        yield "retry: 3000\n\n"
        yield f"event: snapshot\ndata: {_sdrs_state.status_response().model_dump_json()}\n\n"
        while True:
            yield await queue.get()
    finally:
        _subscriber_queues.discard(queue)


@app.get("/api/events")
async def mock_events() -> StreamingResponse:
    """Serve the scripted SSE stream: an initial snapshot, then the hotplug/health script."""
    return StreamingResponse(
        _subscriber_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ── Hotspot (ADR-0007) ────────────────────────────────────────────────────────
#
# The hardest paths in the hotspot UI — the uplink-loss warning and the
# commit-confirm countdown that rolls back on its own — are exactly the ones
# that need a Raspberry Pi with two radios to reach for real. So the mock
# implements them properly rather than stubbing them: a real confirmation
# window, a real timer, a real rollback, and a real `notice` broadcast when it
# fires. That is what makes the whole flow developable on a laptop.

MOCK_HOTSPOT_CONFIRM_TIMEOUT_S = 45.0
"""Shorter than production's 120s so a developer is not waiting two minutes to
watch the rollback they are trying to build the UI for."""

MOCK_GATEWAY_CIDR = "10.42.0.1/24"

_MOCK_SCENARIOS = frozenset(
    {"ok", "unavailable", "command_failed", "no_wireless_interface", "auth_token_missing"}
)
"""Set with `?scenario=` on any hotspot route to reach an error branch that would
otherwise need broken hardware. Mirrors the existing hotplug-script idiom."""

_MOCK_INTERFACES = (
    # wlan0 carries the uplink, so choosing it must raise the "this will drop
    # your connection" warning; wlan1 is idle and should be auto-selected.
    WirelessInterfaceItem(
        name="wlan0",
        mac_address="b8:27:eb:11:22:33",
        supports_ap=True,
        state="connected",
        station_ssid="Home-2G",
        ipv4_addresses=("192.168.1.45/24",),
        carries_default_route=True,
        in_use_by="Home-2G",
    ),
    WirelessInterfaceItem(
        name="wlan1",
        mac_address="b8:27:eb:44:55:66",
        supports_ap=True,
        state="disconnected",
        station_ssid=None,
        ipv4_addresses=(),
        carries_default_route=False,
        in_use_by=None,
    ),
)


class MockHotspotState:
    """The mock's in-memory hotspot.

    Holds `passphrase_set` and **never a passphrase**, exactly like the real
    thing — a mock that stashed the secret would quietly teach the frontend a
    habit the real API does not permit.
    """

    def __init__(self) -> None:
        self.configured = False
        self.ssid: str | None = None
        self.hidden = True
        self.security = "wpa2"
        self.band = "bg"
        self.channel = 0
        self.interface: str | None = None
        self.gateway_cidr: str | None = None
        self.passphrase_set = False
        self.active = False
        self.autoconnect = False
        self.pending_confirmation = False
        self.confirm_deadline_ms: int | None = None
        self.leases: list[HotspotClientItem] = []
        self.rollback_task: asyncio.Task[None] | None = None
        self.lease_task: asyncio.Task[None] | None = None


_hotspot_state = MockHotspotState()


def _hotspot_scenario(request: Request) -> str:
    """Read the `?scenario=` knob, defaulting to the happy path."""
    scenario = request.query_params.get("scenario", "ok")
    return scenario if scenario in _MOCK_SCENARIOS else "ok"


def _hotspot_state_response(scenario: str = "ok") -> HotspotStateResponse:
    """Assemble the current mock `GET /api/hotspot` body."""
    state = _hotspot_state
    warnings: list[HotspotWarning] = []
    if scenario == "unavailable":
        warnings.append("nm_unavailable")
    if scenario == "auth_token_missing":
        warnings.append("auth_token_missing")
    if state.interface == "wlan0":
        warnings.append("single_radio_uplink_loss")

    return HotspotStateResponse(
        available=scenario != "unavailable",
        control_enabled=True,
        auth_token_configured=scenario != "auth_token_missing",
        configured=state.configured,
        enabled=state.autoconnect,
        active=state.active,
        interface=state.interface,
        ssid=state.ssid,
        hidden=state.hidden,
        security=state.security,  # type: ignore[arg-type]
        band=state.band,  # type: ignore[arg-type]
        channel=state.channel,
        gateway_address=state.gateway_cidr.split("/", 1)[0] if state.gateway_cidr else None,
        gateway_cidr=state.gateway_cidr,
        passphrase_set=state.passphrase_set,
        uplink_interface_is_hotspot_interface=state.interface == "wlan0",
        pending_confirmation=state.pending_confirmation,
        confirm_deadline_ms=state.confirm_deadline_ms,
        last_error=None,
        warnings=tuple(warnings),
        generated_at=int(time.time() * 1000),
    )


def _hotspot_error(status_code: int, code: str, message: str, **context: object) -> HTTPException:
    """Build a hotspot error in the uniform envelope the real router uses."""
    return HTTPException(status_code=status_code, detail=error_detail(code, message, **context))


def _guard_hotspot_scenario(scenario: str) -> None:
    """Raise whichever failure the requested scenario is meant to reproduce."""
    if scenario == "unavailable":
        raise _hotspot_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "hotspot_unavailable",
            "This host cannot manage a WiFi hotspot: NetworkManager was not reachable.",
        )
    if scenario == "auth_token_missing":
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "auth_token_required",
            "Set SENTRY_AUTH_TOKEN before starting a hotspot.",
        )
    if scenario == "no_wireless_interface":
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "no_wireless_interface",
            "This host has no wireless interface that can host a network.",
        )
    if scenario == "command_failed":
        raise _hotspot_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "hotspot_command_failed",
            "The network command failed.",
            stderr_tail="Error: Connection activation failed: (7) Secrets were required.",
        )


def _choose_mock_interface(requested: str | None, confirm_uplink_loss: bool) -> str:
    """Mirror the real service's selection rule, including its refusal."""
    if requested is None:
        idle = [entry for entry in _MOCK_INTERFACES if not entry.carries_default_route]
        if idle:
            return idle[0].name
        requested = _MOCK_INTERFACES[0].name

    match = next((entry for entry in _MOCK_INTERFACES if entry.name == requested), None)
    if match is None:
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "interface_not_found",
            f"No wireless interface named {requested} was found.",
            interface=requested,
            available=[entry.name for entry in _MOCK_INTERFACES],
        )
    in_use = match.in_use_by is not None or match.carries_default_route
    if in_use and not confirm_uplink_loss:
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "uplink_loss_unconfirmed",
            f"{match.name} is currently connected to {match.station_ssid or 'a network'}. "
            "Starting the hotspot will disconnect it. Confirm to continue.",
            interface=match.name,
            station_ssid=match.station_ssid,
            carries_default_route=match.carries_default_route,
        )
    return match.name


async def _mock_rollback_after_timeout() -> None:
    """Undo an unconfirmed activation, exactly as the real rollback timer does."""
    await asyncio.sleep(MOCK_HOTSPOT_CONFIRM_TIMEOUT_S)
    _hotspot_state.active = False
    _hotspot_state.autoconnect = False
    _hotspot_state.pending_confirmation = False
    _hotspot_state.confirm_deadline_ms = None
    _hotspot_state.rollback_task = None
    _cancel_mock_lease_growth()
    _hotspot_state.leases.clear()
    _broadcast(
        "notice",
        json.loads(
            NoticeItem(
                level="warn",
                code="hotspot_rollback",
                message="The hotspot was not confirmed in time and has been rolled back.",
                device_id=None,
                ts=int(time.time() * 1000),
            ).model_dump_json()
        ),
    )


async def _mock_grow_leases() -> None:
    """Add a client a few seconds after the hotspot comes up, so the list is not static."""
    await asyncio.sleep(10.0)
    _hotspot_state.leases.append(
        HotspotClientItem(
            mac_address="a4:83:e7:9c:1d:02",
            ip_address="10.42.0.37",
            hostname="sentinel-laptop",
            lease_expires_at_ms=int(time.time() * 1000) + 3_600_000,
            expired=False,
        )
    )
    await asyncio.sleep(15.0)
    _hotspot_state.leases.append(
        HotspotClientItem(
            mac_address="f0:18:98:44:55:66",
            ip_address="10.42.0.51",
            hostname=None,
            lease_expires_at_ms=int(time.time() * 1000) - 60_000,
            expired=True,
        )
    )


def _cancel_mock_rollback() -> None:
    """Cancel any armed rollback and clear its window."""
    task = _hotspot_state.rollback_task
    _hotspot_state.rollback_task = None
    _hotspot_state.pending_confirmation = False
    _hotspot_state.confirm_deadline_ms = None
    if task is not None:
        task.cancel()


def _cancel_mock_lease_growth() -> None:
    """Stop the scripted lease-growth task."""
    task = _hotspot_state.lease_task
    _hotspot_state.lease_task = None
    if task is not None:
        task.cancel()


def _activate_mock_hotspot() -> None:
    """Bring the mock hotspot up provisionally and arm its rollback."""
    _cancel_mock_rollback()
    _cancel_mock_lease_growth()
    _hotspot_state.active = True
    _hotspot_state.pending_confirmation = True
    _hotspot_state.confirm_deadline_ms = int(
        time.time() * 1000 + MOCK_HOTSPOT_CONFIRM_TIMEOUT_S * 1000
    )
    _hotspot_state.rollback_task = asyncio.create_task(_mock_rollback_after_timeout())
    _hotspot_state.lease_task = asyncio.create_task(_mock_grow_leases())


@app.get("/api/hotspot", response_model=HotspotStateResponse)
async def mock_get_hotspot(request: Request) -> HotspotStateResponse:
    """Serve the current mock hotspot state; always 200, like the real route."""
    return _hotspot_state_response(_hotspot_scenario(request))


@app.get("/api/hotspot/interfaces", response_model=WirelessInterfacesResponse)
async def mock_hotspot_interfaces(request: Request) -> WirelessInterfacesResponse:
    """List the two scripted radios, or none under the `no_wireless_interface` scenario."""
    scenario = _hotspot_scenario(request)
    interfaces = () if scenario in {"unavailable", "no_wireless_interface"} else _MOCK_INTERFACES
    return WirelessInterfacesResponse(interfaces=interfaces, generated_at=int(time.time() * 1000))


@app.get("/api/hotspot/clients", response_model=HotspotClientsResponse)
async def mock_hotspot_clients(request: Request) -> HotspotClientsResponse:
    """Serve the scripted lease list, or `null` when the host could not be asked.

    `null` and `[]` stay distinct here for the same reason they do in the real
    route: the UI renders "cannot tell" differently from "nobody connected",
    and a mock that collapsed them would leave that branch untested.
    """
    if _hotspot_scenario(request) == "unavailable":
        return HotspotClientsResponse(clients=None, generated_at=int(time.time() * 1000))
    return HotspotClientsResponse(
        clients=tuple(_hotspot_state.leases), generated_at=int(time.time() * 1000)
    )


@app.put("/api/hotspot", response_model=HotspotStateResponse)
async def mock_put_hotspot(request: Request, config: HotspotConfigRequest) -> HotspotStateResponse:
    """Apply a whole hotspot configuration, honouring the write-only passphrase rule."""
    scenario = _hotspot_scenario(request)
    _guard_hotspot_scenario(scenario)

    if config.passphrase is None and not _hotspot_state.passphrase_set:
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "passphrase_required",
            "Set a password for the hotspot before enabling it.",
            reason="no_stored_passphrase",
        )

    interface = _choose_mock_interface(config.interface, config.confirm_uplink_loss)

    state = _hotspot_state
    state.configured = True
    state.ssid = config.ssid
    state.hidden = config.hidden
    state.security = config.security
    state.band = config.band
    state.channel = config.channel
    state.interface = interface
    state.gateway_cidr = config.gateway_cidr or MOCK_GATEWAY_CIDR
    # Never stores the value — only that one exists.
    state.passphrase_set = state.passphrase_set or config.passphrase is not None

    if config.enabled:
        _activate_mock_hotspot()
    else:
        _cancel_mock_rollback()
        _cancel_mock_lease_growth()
        state.active = False
        state.autoconnect = False
        state.leases.clear()
    return _hotspot_state_response(scenario)


@app.post("/api/hotspot/enable", response_model=HotspotStateResponse)
async def mock_enable_hotspot(
    request: Request, activation: HotspotActivationRequest
) -> HotspotStateResponse:
    """Start the mock hotspot provisionally."""
    scenario = _hotspot_scenario(request)
    _guard_hotspot_scenario(scenario)
    if not _hotspot_state.configured:
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "hotspot_not_configured",
            "Configure the hotspot's network name and password first.",
        )
    _hotspot_state.interface = _choose_mock_interface(
        _hotspot_state.interface, activation.confirm_uplink_loss
    )
    _activate_mock_hotspot()
    return _hotspot_state_response(scenario)


@app.post("/api/hotspot/disable", response_model=HotspotStateResponse)
async def mock_disable_hotspot(
    request: Request, activation: HotspotActivationRequest
) -> HotspotStateResponse:
    """Stop the mock hotspot."""
    scenario = _hotspot_scenario(request)
    _guard_hotspot_scenario(scenario)
    _cancel_mock_rollback()
    _cancel_mock_lease_growth()
    _hotspot_state.active = False
    _hotspot_state.autoconnect = False
    _hotspot_state.leases.clear()
    return _hotspot_state_response(scenario)


@app.post("/api/hotspot/confirm", response_model=HotspotStateResponse)
async def mock_confirm_hotspot(request: Request) -> HotspotStateResponse:
    """Keep the hotspot on trial and make it persistent."""
    scenario = _hotspot_scenario(request)
    if _hotspot_state.rollback_task is None:
        raise _hotspot_error(
            status.HTTP_409_CONFLICT,
            "no_pending_confirmation",
            "There is no hotspot change waiting to be confirmed.",
        )
    _cancel_mock_rollback()
    _hotspot_state.autoconnect = True
    return _hotspot_state_response(scenario)


@app.delete("/api/hotspot", status_code=status.HTTP_204_NO_CONTENT)
async def mock_delete_hotspot(request: Request) -> Response:
    """Forget the mock hotspot entirely, password included."""
    _guard_hotspot_scenario(_hotspot_scenario(request))
    _cancel_mock_rollback()
    _cancel_mock_lease_growth()
    global _hotspot_state
    _hotspot_state = MockHotspotState()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
