"""Device schemas: the realtime status view, the config-centric list, and PATCH.

Shapes are frozen exactly to architecture §7.2, §7.4 and §7.5. `DeviceStatus`
backs both `GET /api/status` and the SSE `snapshot`/`device_changed` payloads;
`DeviceRecord` backs `GET /api/devices` and the `PATCH` response.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DeviceState = Literal[
    "detected", "configured", "starting", "streaming", "degraded", "stopped", "error"
]
"""The device status state machine's states (architecture §10)."""

IdentityKind = Literal["serial", "usb"]
"""Which persistence-key tier a device is currently keyed by (ADR-0003)."""

# librtlsdr-supported sample rates (architecture §7.5). Any other value is a
# 400 validation_error; rates above 2_400_000 are accepted but the service
# layer raises a `notice` warning about USB sample drops on a Pi.
ALLOWED_SAMPLE_RATES: frozenset[int] = frozenset(
    {
        250_000,
        1_024_000,
        1_200_000,
        1_536_000,
        1_800_000,
        1_920_000,
        2_048_000,
        2_160_000,
        2_400_000,
        2_560_000,
        2_880_000,
        3_200_000,
    }
)

DEVICE_NAME_PATTERN = r"^[A-Za-z0-9 _.\-()/]+$"
"""Allow-list for operator-assigned device names (architecture §7.5)."""

# Direct-sampling modes exposed by rtl_tcp's `-D` flag: 0 = off (default
# tuner path), 1 = I-branch ADC, 2 = Q-branch ADC. Open question §13.5 is
# settled in scope now (bias-tee and direct sampling are nullable throughout).
DirectSamplingMode = Literal[0, 1, 2]


class UsbInfo(BaseModel):
    """The live USB descriptor and topology for a present device (architecture §7.2)."""

    model_config = ConfigDict(frozen=True)

    topology_path: str = Field(description='Bus-port path, e.g. "1-1.4.2"')
    bus_number: int = Field(ge=0)
    port_chain: tuple[int, ...] = Field(description="The port path as integers, e.g. (1, 4, 2)")
    hub_depth: int = Field(ge=0, description="len(port_chain) - 1")
    device_address: int = Field(description="Kernel devnum; unstable, display only")
    vendor_id: str = Field(description='Lowercase hex, no "0x", e.g. "0bda"')
    product_id: str = Field(description='Lowercase hex, no "0x", e.g. "2838"')
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = Field(default=None, description="The raw reported iSerial")
    driver: str | None = Field(default=None, description="Bound kernel driver name, if any")
    driver_conflict: bool = Field(
        description="True when the DVB kernel driver is bound instead of the userspace driver"
    )


class UsbLastKnownInfo(BaseModel):
    """A reduced USB description for a configured device that is currently absent.

    Populated from the persisted `last_*` columns so an absent device still
    renders identifiably in the UI (architecture §7.2).
    """

    model_config = ConfigDict(frozen=True)

    topology_path: str
    vendor_id: str
    product_id: str
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = None


class OutputInfo(BaseModel):
    """The public IQ/control endpoint for a configured device."""

    model_config = ConfigDict(frozen=True)

    host: str = Field(description="The Pi's advertised LAN address")
    iq_port: int = Field(ge=1024, le=65533, description="The relay's public IQ port P")
    control_port: int = Field(ge=1026, le=65535, description="P + 2, the NDJSON control port")


class TunerInfo(BaseModel):
    """The live tuner state as last observed via `control_follower` (architecture §7.2)."""

    model_config = ConfigDict(frozen=True)

    center_hz: int
    sample_rate: int
    gain_db: float
    gain_auto: bool
    locked: bool = Field(description="Whether another owner currently holds the tuning token")
    observed_at: int = Field(description="Unix ms this state was last observed on P+2")
    bias_tee: bool | None = Field(
        default=None, description="Bias-T power state, when the dongle supports it"
    )
    direct_sampling: DirectSamplingMode | None = Field(
        default=None, description="Direct-sampling mode (0=off, 1=I-ADC, 2=Q-ADC), when in use"
    )


class ProcessInfo(BaseModel):
    """Supervisor-owned process/lifecycle telemetry for a device's running pair."""

    model_config = ConfigDict(frozen=True)

    rtl_tcp_pid: int | None = None
    relay_pid: int | None = None
    internal_port: int | None = Field(default=None, description="The loopback rtl_tcp port")
    restarts: int = Field(ge=0, default=0)
    last_restart_at: int | None = None
    last_exit_code: int | None = None


class ClientCounts(BaseModel):
    """Per-port connected-client counts from `SocketStatsSource`.

    Every field is nullable and advisory: `None` on platforms without
    `/proc/net/tcp` (architecture decision — always nullable, never a hard
    dependency for status reporting).
    """

    model_config = ConfigDict(frozen=True)

    iq: int | None = None
    control: int | None = None


class DeviceStatus(BaseModel):
    """One device's realtime status — the `GET /api/status` and SSE payload shape."""

    model_config = ConfigDict(frozen=True)

    device_id: str = Field(description='The public key: "serial:<value>" or "usb:<path>"')
    record_id: int | None = Field(description="The DB surrogate key; null for a detected device")
    identity_kind: IdentityKind
    identity_key: str
    needs_identification: bool
    name: str
    description: str
    state: DeviceState
    state_since: int = Field(description="Unix ms this state began")
    state_reason: str | None = Field(default=None, description="Machine code, non-null in error")
    present: bool
    enabled: bool
    usb: UsbInfo | None = Field(default=None, description="Null when the device is absent")
    usb_last_known: UsbLastKnownInfo | None = Field(
        default=None, description="Populated instead of `usb` for an absent configured device"
    )
    output: OutputInfo | None = Field(default=None, description="Null for an unconfigured device")
    tuner: TunerInfo | None = Field(
        default=None, description="Null until control_follower's first state event"
    )
    processes: ProcessInfo | None = None
    clients: ClientCounts | None = None
    last_seen_at: int | None = None


class StatusResponse(BaseModel):
    """`GET /api/status` and the SSE `snapshot` event body."""

    model_config = ConfigDict(frozen=True)

    generated_at: int = Field(description="Unix ms this snapshot was assembled")
    sdrs: tuple[DeviceStatus, ...] = Field(
        description="Sorted by usb.topology_path; absent devices last"
    )


class DeviceRecord(BaseModel):
    """One device's configuration-centric record — `GET /api/devices` item and PATCH response."""

    model_config = ConfigDict(frozen=True)

    device_id: str
    record_id: int | None
    identity_kind: IdentityKind
    identity_key: str
    name: str
    description: str
    output_port: int | None = None
    control_port: int | None = None
    enabled: bool
    center_hz: int | None = None
    sample_rate: int | None = None
    gain_db: float | None = None
    gain_auto: bool
    ppm_correction: int
    bias_tee: bool | None = Field(default=None, description="Bias-T power, nullable")
    direct_sampling: DirectSamplingMode | None = Field(
        default=None, description="Direct-sampling mode, nullable"
    )
    present: bool
    needs_identification: bool
    state: DeviceState
    last_topology_path: str
    last_serial: str
    last_seen_at: int | None = None
    created_at: int
    updated_at: int


class PortConstraints(BaseModel):
    """Mirrors the port-allocator rule table so the UI can validate inline.

    Advisory only — the server always re-validates on `PATCH` (architecture §7.4).
    """

    model_config = ConfigDict(frozen=True)

    port_min: int
    port_max: int
    reserved: tuple[int, ...]
    internal_range: tuple[int, int]
    in_use: tuple[int, ...]


class DevicesListResponse(BaseModel):
    """`GET /api/devices` body: every configured and every detected device."""

    model_config = ConfigDict(frozen=True)

    devices: tuple[DeviceRecord, ...]
    port_suggestion: int | None
    constraints: PortConstraints


class DevicePatch(BaseModel):
    """`PATCH /api/devices/{device_id}` request body — all fields optional, one required.

    `extra="forbid"` rejects unknown fields outright rather than silently
    ignoring operator typos (architecture §12.12).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    output_port: int | None = Field(default=None, ge=1024, le=65533)
    enabled: bool | None = None
    center_hz: int | None = Field(default=None, ge=24_000_000, le=1_766_000_000)
    sample_rate: int | None = None
    gain_db: float | None = Field(default=None, ge=0.0, le=50.0)
    gain_auto: bool | None = None
    ppm_correction: int | None = Field(default=None, ge=-200, le=200)
    bias_tee: bool | None = None
    direct_sampling: DirectSamplingMode | None = None

    @field_validator("name")
    @classmethod
    def _strip_and_validate_name(cls, value: str | None) -> str | None:
        """Strip whitespace, then re-check the length and allow-list against it."""
        if value is None:
            return None
        stripped = value.strip()
        if not (1 <= len(stripped) <= 64):
            raise ValueError("name must be 1-64 characters after stripping whitespace")
        if not re.match(DEVICE_NAME_PATTERN, stripped):
            raise ValueError("name may contain only letters, digits, spaces and _ . - ( ) /")
        return stripped

    @field_validator("sample_rate")
    @classmethod
    def _validate_sample_rate(cls, value: int | None) -> int | None:
        """Reject any rate librtlsdr does not support."""
        if value is not None and value not in ALLOWED_SAMPLE_RATES:
            raise ValueError(f"sample_rate must be one of {sorted(ALLOWED_SAMPLE_RATES)}")
        return value

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> DevicePatch:
        """Enforce "at least one field required" (architecture §7.5)."""
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be supplied")
        return self
