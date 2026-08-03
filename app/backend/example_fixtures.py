"""Fixed example payloads shared by the Phase 0 router stubs.

Not used by any real service — this module exists purely so
`GET /api/status`, `GET /api/devices` and friends return a single,
consistent, schema-valid example while their services are still
`NotImplementedError` stubs, which is what lets `openapi.json` generate with
realistic examples and lets the app be smoke-tested before Phase 1 lands.
"""

from __future__ import annotations

from app.backend.schemas.device import (
    ClientCounts,
    DeviceRecord,
    DeviceStatus,
    OutputInfo,
    ProcessInfo,
    TunerInfo,
    UsbInfo,
)
from app.backend.schemas.health import DeviceCounts, HealthResponse, HotplugHealth
from app.backend.schemas.sdr_export import SdrExportItem, SdrExportSource

EXAMPLE_DEVICE_ID = "serial:ADSB-01"
SENTRY_VERSION = "0.1.0"

EXAMPLE_USB_INFO = UsbInfo(
    topology_path="1-1.4.2",
    bus_number=1,
    port_chain=(1, 4, 2),
    hub_depth=2,
    device_address=7,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="Realtek",
    product="RTL2838UHIDIR",
    serial="ADSB-01",
    driver="rtl2832u",
    driver_conflict=False,
)

EXAMPLE_DEVICE_STATUS = DeviceStatus(
    device_id=EXAMPLE_DEVICE_ID,
    record_id=3,
    identity_kind="serial",
    identity_key="ADSB-01",
    needs_identification=False,
    name="ADSB SDR",
    description="Roof, 1090 MHz",
    state="streaming",
    state_since=1753789200000,
    state_reason=None,
    present=True,
    enabled=True,
    # This example device is the one that appears in the export example below,
    # so it must not be private — a private device is never in that list.
    visibility="public",
    usb=EXAMPLE_USB_INFO,
    output=OutputInfo(host="192.168.1.45", iq_port=1234, control_port=1236),
    tuner=TunerInfo(
        center_hz=1090000000,
        sample_rate=2400000,
        gain_db=40.2,
        gain_auto=False,
        locked=True,
        observed_at=1753790120000,
        bias_tee=None,
        direct_sampling=None,
    ),
    processes=ProcessInfo(
        rtl_tcp_pid=812,
        relay_pid=813,
        internal_port=14000,
        restarts=0,
        last_restart_at=None,
        last_exit_code=None,
    ),
    clients=ClientCounts(iq=2, control=1),
    last_seen_at=1753790123000,
)

EXAMPLE_DEVICE_RECORD = DeviceRecord(
    device_id=EXAMPLE_DEVICE_ID,
    record_id=3,
    identity_kind="serial",
    identity_key="ADSB-01",
    name="ADSB SDR",
    description="Roof, 1090 MHz",
    output_port=1234,
    control_port=1236,
    enabled=True,
    visibility="public",
    center_hz=1090000000,
    sample_rate=2400000,
    gain_db=40.2,
    gain_auto=False,
    ppm_correction=0,
    bias_tee=None,
    direct_sampling=None,
    present=True,
    needs_identification=False,
    state="streaming",
    last_topology_path="1-1.4.2",
    last_serial="ADSB-01",
    last_seen_at=1753790123000,
    created_at=1753000000000,
    updated_at=1753789000000,
)

EXAMPLE_HEALTH_RESPONSE = HealthResponse(
    status="ok",
    version=SENTRY_VERSION,
    started_at=1753789000000,
    uptime_s=3612.4,
    database="ok",
    hotplug=HotplugHealth(source="udev", healthy=True, last_event_at=1753790100000),
    devices=DeviceCounts(
        present=1, configured=1, streaming=1, degraded=0, error=0, needs_identification=0
    ),
)

EXAMPLE_SDR_EXPORT_ITEM = SdrExportItem(
    sentry_device_id=EXAMPLE_DEVICE_ID,
    name="ADSB SDR",
    host="192.168.1.45",
    port=1234,
    control_port=1236,
    description="RTL2838UHIDIR @ USB 1-1.4.2",
    notes="Feeder cable due for replacement.",
    antenna="Discone, roof mast",
    enabled=True,
    bandwidth=2400000,
    rf_gain=40.2,
    agc=False,
    available=True,
    state="streaming",
)

EXAMPLE_SDR_EXPORT_SOURCE = SdrExportSource(
    name="sentry", version=SENTRY_VERSION, host="192.168.1.45", http_port=8000
)
