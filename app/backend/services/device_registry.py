"""The in-memory authoritative SDR state (architecture §4.3, §10).

Merges persisted configuration (from `DeviceRepository`) with live presence
(from hotplug) into `DeviceStatus` records, owns every state-machine
transition, and emits `device_changed` on the event bus. The single source of
truth every router reads.

**Live presence wiring.** `hotplug.py` cannot be injected with this class
directly (its constructor is frozen to match the composition root's
`(hotplug_source, usb_discovery, clock, event_bus)` call) — instead it
publishes settled arrivals/departures as internal-only messages on the shared
`EventBus`, and `load()` starts a background task here that subscribes and
applies them via the existing `apply_device_arrived`/`apply_device_departed`
methods. See `hotplug.py`'s module docstring for the full rationale.

**Host resolution note for routers.** `OutputInfo.host` cannot be resolved
here — it depends on `SENTRY_ADVERTISED_HOST` or the current request's `Host`
header (architecture §7.7), neither of which this module has access to. Every
`DeviceStatus.output` built here carries `host=""`; the `status`/`events`
routers (Phase 2B) must overlay the resolved host before serialising a
response, exactly as `/api/v1/sdrs` already must.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Literal, cast

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.repository import DeviceRepository
from app.backend.interfaces.types import PersistedDeviceRow, UsbDeviceSnapshot
from app.backend.schemas.device import (
    DeviceRecord,
    DeviceState,
    DeviceStatus,
    DeviceVisibility,
    OutputInfo,
    ProcessInfo,
    TunerInfo,
    UsbInfo,
    UsbLastKnownInfo,
)
from app.backend.schemas.events import DeviceRemovedEvent
from app.backend.services.event_bus import EventBus, SseMessage
from app.backend.services.hotplug import (
    HOTPLUG_DEVICE_ARRIVED_EVENT,
    HOTPLUG_DEVICE_DEPARTED_EVENT,
    DeviceArrived,
    DeviceDeparted,
    HotplugArrival,
)
from app.backend.services.identity import DeviceIdentity

# States from which a fresh arrival re-arms the supervisor by moving the
# device back to `configured` (architecture §10 rows: stopped -> starting is
# gated on enabled+present, which SupervisorService.reconcile() re-evaluates
# off `configured`; error -> configured is the explicit replug-clears-error row).
# `starting` is included so a device left stuck there — e.g. one that departed
# or was disabled mid-restart-backoff, before `SupervisorService` next settles
# it to `stopped` (see that module's `_handle_pair_exit`) — is not permanently
# unrecoverable to a later replug; without it a stuck `starting` entry would
# never re-arm (finding: SSE resync/registry review, "starting" omission).
_STATES_READY_FOR_RECONCILE: frozenset[DeviceState] = frozenset(
    {"configured", "stopped", "error", "starting"}
)

_VALID_IDENTITY_KINDS: frozenset[str] = frozenset({"serial", "usb"})


class DeviceNotFoundError(Exception):
    """Raised by `apply_patch`/`delete` when `device_id` is neither persisted nor detected."""


class DeviceUnidentifiedError(Exception):
    """Raised by `apply_patch` for a tier-3 (`needs_identification`) device (architecture §7.5)."""


class IncompleteConfigurationError(Exception):
    """Raised by `apply_patch` when a device's *first* PATCH omits a required field.

    A device's row does not exist yet, so there is no persisted `name`/
    `output_port` to fall back to — coercing the missing value to `""`/`0`
    would silently persist a bogus row (and, since `output_port=0` fails
    `OutputInfo`'s `ge=1024` validator, would then crash every future
    `GET /api/status` and SSE snapshot). The router maps this to `422
    incomplete_configuration` naming exactly what is missing, rather than the
    misleading `409 port_conflict` a coerced `0`/`""` used to produce.
    """

    def __init__(self, missing_fields: tuple[str, ...]) -> None:
        super().__init__(f"first configuration is missing required fields: {missing_fields}")
        self.missing_fields = missing_fields


@dataclass(frozen=True, slots=True)
class RunnableDevice:
    """One persisted, enabled, present device — `SupervisorService.reconcile()`'s desired set.

    `serial` is the *raw last-reported* USB serial (architecture §5.3), not
    the persistence `identity_key` — for a tier-2 (topology-keyed) device
    those differ, and it is the raw serial that must match what
    `RtlSdrLibrary.usb_strings()` reports at spawn time.
    """

    device_id: str
    record_id: int
    serial: str
    output_port: int
    control_port: int
    ppm_correction: int
    center_hz: int | None
    sample_rate: int | None
    gain_db: float | None
    gain_auto: bool


@dataclass(slots=True)
class _DeviceEntry:
    """Mutable in-memory record merging persisted config with live presence."""

    device_id: str
    record_id: int | None
    identity_kind: Literal["serial", "usb"]
    identity_key: str
    needs_identification: bool
    name: str
    description: str
    notes: str
    antenna: str
    output_port: int | None
    enabled: bool
    visibility: DeviceVisibility
    center_hz: int | None
    sample_rate: int | None
    gain_db: float | None
    gain_auto: bool
    ppm_correction: int
    bias_tee: bool | None
    direct_sampling: int | None
    present: bool
    state: DeviceState
    state_since: int
    state_reason: str | None
    usb_snapshot: UsbDeviceSnapshot | None
    driver_conflict: bool
    last_topology_path: str
    last_vendor_id: str
    last_product_id: str
    last_manufacturer: str
    last_product: str
    last_serial: str
    last_seen_at: int | None
    pending_replug_until: int | None
    created_at: int
    updated_at: int
    tuner: TunerInfo | None = None
    processes: ProcessInfo | None = None


class DeviceRegistry:
    """Owns every `DeviceStatus` and every transition in the §10 state machine."""

    def __init__(
        self,
        device_repository: DeviceRepository,
        event_bus: EventBus,
        clock: Clock,
    ) -> None:
        self._device_repository = device_repository
        self._event_bus = event_bus
        self._clock = clock
        self._devices: dict[str, _DeviceEntry] = {}
        self._hotplug_subscriber_task: asyncio.Task[None] | None = None

    async def load(self) -> None:
        """Populate in-memory state from persisted rows at startup, before serving traffic.

        Also starts the background task that consumes `hotplug.py`'s
        internal arrival/departure messages off the shared `EventBus` for the
        remainder of the process lifetime (see this module's docstring).
        """
        persisted_rows = await self._device_repository.list_all()
        for row in persisted_rows:
            entry = self._entry_from_row(row)
            self._devices[entry.device_id] = entry
        self._hotplug_subscriber_task = asyncio.create_task(
            self._consume_hotplug_events(), name="device-registry-hotplug-consumer"
        )

    async def close(self) -> None:
        """Stop the background hotplug-consumer task started by `load()`.

        Called by the composition root's lifespan shutdown (`main.py`) after
        every supervised process has been stopped; safe to call multiple
        times or before `load()` regardless.
        """
        if self._hotplug_subscriber_task is not None:
            self._hotplug_subscriber_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._hotplug_subscriber_task
            self._hotplug_subscriber_task = None

    async def _consume_hotplug_events(self) -> None:
        """Forward settled hotplug arrivals/departures from the event bus onto this registry.

        Uses `EventBus.subscribe_internal()` — a dedicated, unbounded
        channel — rather than the public `subscribe()` every browser SSE
        connection also shares. A dropped arrival/departure here would
        silently and permanently desync `present` (and, downstream, the
        supervisor's desired set) with no recovery mechanism, unlike a
        browser tab that can always be handed a fresh `snapshot`; see
        `event_bus.py`'s module docstring for the full rationale.
        """
        async for message in self._event_bus.subscribe_internal():
            if message.event == HOTPLUG_DEVICE_ARRIVED_EVENT and isinstance(
                message.data, HotplugArrival
            ):
                await self.apply_device_arrived(message.data.event, message.data.identity)
            elif message.event == HOTPLUG_DEVICE_DEPARTED_EVENT and isinstance(
                message.data, DeviceDeparted
            ):
                await self.apply_device_departed(message.data)

    def get_status(self, device_id: str) -> DeviceStatus | None:
        """Return one device's current status, or None if it is unknown entirely."""
        entry = self._devices.get(device_id)
        return self._to_device_status(entry) if entry is not None else None

    def list_statuses(self) -> tuple[DeviceStatus, ...]:
        """Return every known device's status, sorted per architecture §7.2."""
        ordered = sorted(self._devices.values(), key=self._status_sort_key)
        return tuple(self._to_device_status(entry) for entry in ordered)

    def list_records(self) -> tuple[DeviceRecord, ...]:
        """Return every known device's configuration-centric record (`GET /api/devices`)."""
        ordered = sorted(self._devices.values(), key=self._status_sort_key)
        return tuple(self._to_device_record(entry) for entry in ordered)

    def list_runnable_devices(self) -> tuple[RunnableDevice, ...]:
        """Return every persisted, enabled, present device — `SupervisorService`'s desired set."""
        runnable: list[RunnableDevice] = []
        for entry in self._devices.values():
            if entry.record_id is None or not entry.enabled or not entry.present:
                continue
            if entry.output_port is None:
                continue
            runnable.append(
                RunnableDevice(
                    device_id=entry.device_id,
                    record_id=entry.record_id,
                    serial=entry.last_serial,
                    output_port=entry.output_port,
                    control_port=entry.output_port + 2,
                    ppm_correction=entry.ppm_correction,
                    center_hz=entry.center_hz,
                    sample_rate=entry.sample_rate,
                    gain_db=entry.gain_db,
                    gain_auto=entry.gain_auto,
                )
            )
        return tuple(runnable)

    async def apply_device_arrived(
        self, event: DeviceArrived, identity: DeviceIdentity | None
    ) -> None:
        """Handle a debounced USB arrival: transition to `detected`, or flag tier 3."""
        now = self._clock.now_ms()

        if identity is None:
            device_id = f"usb:{event.topology_path}"
            entry = self._devices.get(device_id)
            if entry is None:
                entry = _DeviceEntry(
                    device_id=device_id,
                    record_id=None,
                    identity_kind="usb",
                    identity_key=event.topology_path,
                    needs_identification=True,
                    name="Unidentified SDR",
                    description="",
                    notes="",
                    antenna="",
                    output_port=None,
                    enabled=False,
                    # Matches the `sdr_devices.visibility` column default: a
                    # device is never published to Sentinel until an operator
                    # says so.
                    visibility="private",
                    center_hz=None,
                    sample_rate=None,
                    gain_db=None,
                    gain_auto=True,
                    ppm_correction=0,
                    bias_tee=None,
                    direct_sampling=None,
                    present=True,
                    state="detected",
                    state_since=now,
                    state_reason=None,
                    usb_snapshot=event.snapshot,
                    driver_conflict=event.driver_conflict,
                    last_topology_path=event.topology_path,
                    last_vendor_id=event.snapshot.vendor_id,
                    last_product_id=event.snapshot.product_id,
                    last_manufacturer=event.snapshot.manufacturer or "",
                    last_product=event.snapshot.product or "",
                    last_serial=event.snapshot.serial or "",
                    last_seen_at=now,
                    pending_replug_until=None,
                    created_at=now,
                    updated_at=now,
                )
                self._devices[device_id] = entry
            else:
                entry.needs_identification = True
                self._apply_live_presence(entry, event, now)
            self._publish_device_changed(entry)
            return

        device_id = identity.device_id
        entry = self._devices.get(device_id)
        if entry is None:
            persisted_row = await self._device_repository.get_by_identity(
                identity.kind, identity.key
            )
            if persisted_row is not None:
                entry = self._entry_from_row(persisted_row)
            else:
                entry = _DeviceEntry(
                    device_id=device_id,
                    record_id=None,
                    identity_kind=identity.kind,
                    identity_key=identity.key,
                    needs_identification=False,
                    name="",
                    description="",
                    notes="",
                    antenna="",
                    output_port=None,
                    # Matches the `sdr_devices.enabled` column's own default
                    # (architecture §6.1) — an operator's first PATCH need not
                    # repeat `enabled: true` for the device to actually run.
                    enabled=True,
                    # Unlike `enabled`, this does *not* mirror a "convenient"
                    # default — see the column docstring; publishing is opt-in.
                    visibility="private",
                    center_hz=None,
                    sample_rate=None,
                    gain_db=None,
                    gain_auto=True,
                    ppm_correction=0,
                    bias_tee=None,
                    direct_sampling=None,
                    present=False,
                    state="detected",
                    state_since=now,
                    state_reason=None,
                    usb_snapshot=None,
                    driver_conflict=False,
                    last_topology_path="",
                    last_vendor_id="",
                    last_product_id="",
                    last_manufacturer="",
                    last_product="",
                    last_serial="",
                    last_seen_at=None,
                    pending_replug_until=None,
                    created_at=now,
                    updated_at=now,
                )
            self._devices[device_id] = entry

        entry.needs_identification = False
        self._apply_live_presence(entry, event, now)
        if entry.record_id is None:
            self._set_state(entry, "detected", None)
        elif entry.state in _STATES_READY_FOR_RECONCILE:
            self._set_state(entry, "configured", None)
        # Active states (starting/streaming/degraded) are left untouched —
        # this arrival is a duplicate/refresh of presence already known.
        self._publish_device_changed(entry)

    async def apply_device_departed(self, event: DeviceDeparted) -> None:
        """Handle a debounced USB removal per the device's current state (architecture §10)."""
        entry = self._find_entry_by_topology(event.topology_path)
        if entry is None:
            return

        if entry.record_id is None:
            del self._devices[entry.device_id]
            self._event_bus.publish(
                SseMessage(
                    event="device_removed",
                    data=DeviceRemovedEvent(device_id=entry.device_id, record_id=None),
                )
            )
            return

        entry.present = False
        entry.usb_snapshot = None
        entry.needs_identification = False
        reason = "disabled" if not entry.enabled else "device_absent"
        self._set_state(entry, "stopped", reason)
        self._publish_device_changed(entry)

    async def apply_patch(self, device_id: str, patch: dict[str, object]) -> DeviceRecord:
        """Apply a validated `PATCH` to a device, creating its row on first configuration.

        Raises a service-level exception (mapped by the router to the
        matching `409`/`422`) on a port or name conflict, or on an attempt to
        configure a tier-3 (`needs_identification`) device.
        """
        identity_kind, separator, identity_key = device_id.partition(":")
        if not separator or not identity_key or identity_kind not in _VALID_IDENTITY_KINDS:
            # Validated here, at the edge of a client-supplied path parameter,
            # rather than trusted straight into the `Literal["serial", "usb"]`
            # cast below — an unchecked cast is a lie to the type checker, not
            # a guarantee, and a bogus prefix would otherwise reach the
            # database and fail the `ck_sdr_devices_identity_kind` CHECK with
            # a confusing 500 instead of an honest 404.
            raise DeviceNotFoundError(device_id)

        entry = self._devices.get(device_id)
        if entry is None:
            persisted_row = await self._device_repository.get_by_identity(
                identity_kind, identity_key
            )
            if persisted_row is None:
                raise DeviceNotFoundError(device_id)
            entry = self._entry_from_row(persisted_row)
            self._devices[device_id] = entry
        elif entry.needs_identification:
            raise DeviceUnidentifiedError(device_id)

        was_first_configuration = entry.record_id is None
        if was_first_configuration:
            # A brand-new row has no persisted `name`/`output_port` to fall
            # back to. Silently coercing an omitted field to `""`/`0` (the
            # previous behaviour) persisted a bogus row that a CHECK
            # constraint then rejected with a misleading `409 port_conflict`
            # — or, without that constraint, would have crashed every future
            # status read (`OutputInfo.iq_port` requires `>= 1024`). Refuse
            # explicitly instead: the UI is expected to send one combined
            # PATCH for a device's first configuration; a partial one gets an
            # honest, actionable error naming what is missing.
            missing_fields = tuple(
                field_name
                for field_name in ("name", "output_port")
                if patch.get(field_name) is None
            )
            if missing_fields:
                raise IncompleteConfigurationError(missing_fields)

        # `patch` arrives as `dict[str, object]` (the router's job is to hand
        # over an already-`DevicePatch`-validated mapping), so every value
        # extracted from it is `cast` to the type that Pydantic validation
        # already guarantees rather than re-checked here.
        output_port_value = patch.get("output_port", entry.output_port)
        ppm_correction_value = patch.get("ppm_correction", entry.ppm_correction)

        now = self._clock.now_ms()
        row_to_write = PersistedDeviceRow(
            id=entry.record_id or 0,
            identity_kind=cast(Literal["serial", "usb"], identity_kind),
            identity_key=identity_key,
            name=str(patch.get("name", entry.name)),
            description=str(patch.get("description", entry.description)),
            notes=str(patch.get("notes", entry.notes)),
            antenna=str(patch.get("antenna", entry.antenna)),
            # `was_first_configuration` guarantees `output_port_value` is a
            # real int by this point (never None) — the guard above already
            # rejected a first PATCH omitting it, so there is no `or 0`
            # fallback left to silently fabricate a value.
            output_port=int(cast(int, output_port_value)),
            enabled=bool(patch.get("enabled", entry.enabled)),
            visibility=cast(DeviceVisibility, patch.get("visibility", entry.visibility)),
            center_hz=cast("int | None", patch.get("center_hz", entry.center_hz)),
            sample_rate=cast("int | None", patch.get("sample_rate", entry.sample_rate)),
            gain_db=cast("float | None", patch.get("gain_db", entry.gain_db)),
            gain_auto=bool(patch.get("gain_auto", entry.gain_auto)),
            ppm_correction=int(cast(int, ppm_correction_value)),
            bias_tee=cast("bool | None", patch.get("bias_tee", entry.bias_tee)),
            direct_sampling=cast("int | None", patch.get("direct_sampling", entry.direct_sampling)),
            last_topology_path=entry.last_topology_path,
            last_vendor_id=entry.last_vendor_id,
            last_product_id=entry.last_product_id,
            last_manufacturer=entry.last_manufacturer,
            last_product=entry.last_product,
            last_serial=entry.last_serial,
            last_seen_at=entry.last_seen_at,
            pending_replug_until=entry.pending_replug_until,
            created_at=entry.created_at if entry.record_id is not None else now,
            updated_at=now,
        )
        updated_row = await self._device_repository.upsert(row_to_write)

        entry.record_id = updated_row.id
        entry.name = updated_row.name
        entry.description = updated_row.description
        entry.notes = updated_row.notes
        entry.antenna = updated_row.antenna
        entry.output_port = updated_row.output_port
        entry.enabled = updated_row.enabled
        entry.visibility = updated_row.visibility
        entry.center_hz = updated_row.center_hz
        entry.sample_rate = updated_row.sample_rate
        entry.gain_db = updated_row.gain_db
        entry.gain_auto = updated_row.gain_auto
        entry.ppm_correction = updated_row.ppm_correction
        entry.bias_tee = updated_row.bias_tee
        entry.direct_sampling = updated_row.direct_sampling
        entry.created_at = updated_row.created_at
        entry.updated_at = updated_row.updated_at
        if was_first_configuration:
            self._set_state(entry, "configured", None)

        self._publish_device_changed(entry)
        return self._to_device_record(entry)

    async def delete(self, device_id: str) -> None:
        """Remove a device's persisted configuration.

        Does **not** itself stop any running pair — this registry has no
        reference to `SupervisorService` by design (architecture §4.3's
        dependency direction runs the other way). `routers/devices.py`'s
        `DELETE` handler refuses this call entirely while the device is
        `present` (`409 device_present`), so in practice a live pair is never
        torn down by surprise from here; the `if entry.present:` branch below
        exists only for a hypothetical non-HTTP caller and is unreachable via
        the API today.
        """
        entry = self._devices.get(device_id)
        if entry is None or entry.record_id is None:
            return
        record_id = entry.record_id
        await self._device_repository.delete(record_id)

        if entry.present:
            entry.record_id = None
            entry.output_port = None
            entry.enabled = False
            entry.needs_identification = False
            self._set_state(entry, "detected", None)
            self._publish_device_changed(entry)
        else:
            del self._devices[device_id]
            self._event_bus.publish(
                SseMessage(
                    event="device_removed",
                    data=DeviceRemovedEvent(device_id=device_id, record_id=record_id),
                )
            )

    async def migrate_identity_after_flash(
        self, device_id: str, new_serial: str, pending_replug_window_s: float
    ) -> DeviceRecord | None:
        """Move a persisted device's identity to `serial:<new_serial>` after an EEPROM flash.

        `EepromService.flash_serial` calls this once `rtl_eeprom -s` reports
        success (ADR-0003): the dongle now reports a different serial, so its
        row's `(identity_kind, identity_key)` — and therefore its public
        `device_id` — must move with it, or the flash would silently orphan
        the old row and strand the operator's name/port/tuning configuration.
        The migrated entry is marked `pending_replug_until` (architecture
        §7.6) so its absence is not alarmed on until the operator has had a
        chance to physically replug it and the new serial is enumerated.

        Returns `None` if `device_id` has no persisted configuration to
        migrate (nothing to do) — a flash is only ever accepted for a known
        device (`routers/devices.py`), so this is a defensive check, not an
        expected path.
        """
        entry = self._devices.get(device_id)
        if entry is None or entry.record_id is None:
            return None

        assert entry.output_port is not None  # guaranteed once record_id is set
        now = self._clock.now_ms()
        new_device_id = f"serial:{new_serial}"
        row_to_write = PersistedDeviceRow(
            id=entry.record_id,
            identity_kind="serial",
            identity_key=new_serial,
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
            last_topology_path=entry.last_topology_path,
            last_vendor_id=entry.last_vendor_id,
            last_product_id=entry.last_product_id,
            last_manufacturer=entry.last_manufacturer,
            last_product=entry.last_product,
            last_serial=new_serial,
            last_seen_at=entry.last_seen_at,
            pending_replug_until=now + int(pending_replug_window_s * 1000),
            created_at=entry.created_at,
            updated_at=now,
        )
        updated_row = await self._device_repository.upsert(row_to_write)

        del self._devices[device_id]
        entry.device_id = new_device_id
        entry.identity_kind = "serial"
        entry.identity_key = new_serial
        entry.last_serial = new_serial
        entry.pending_replug_until = updated_row.pending_replug_until
        entry.updated_at = updated_row.updated_at
        # The flash requires the pair to already be stopped and the dongle is
        # about to be replugged for the new serial to take effect — settle it
        # here rather than leaving whatever state it was in before the flash.
        entry.present = False
        entry.usb_snapshot = None
        self._set_state(entry, "stopped", "pending_replug")
        self._devices[new_device_id] = entry
        self._publish_device_changed(entry)
        return self._to_device_record(entry)

    async def transition(self, device_id: str, new_state: DeviceState, reason: str | None) -> None:
        """Move one device to `new_state`, stamp `state_since`, and emit `device_changed`.

        Callers (the supervisor, control_follower, eeprom) are responsible
        for only requesting transitions valid per the architecture §10 table;
        this method does not itself validate the transition graph.
        """
        entry = self._devices.get(device_id)
        if entry is None:
            return
        self._set_state(entry, new_state, reason)
        self._publish_device_changed(entry)

    def update_tuner_state(self, device_id: str, tuner: TunerInfo) -> None:
        """Feed a live tuner reading from `control_follower` into one device's status.

        Not part of the architecture §4.3 method list frozen at Phase 0, but
        required for `control_follower` to have anywhere to put what it
        observes — added here since both modules are under the same owner.
        """
        entry = self._devices.get(device_id)
        if entry is None:
            return
        entry.tuner = tuner
        self._publish_device_changed(entry)

    def update_process_info(self, device_id: str, processes: ProcessInfo | None) -> None:
        """Feed supervisor-owned process/lifecycle bookkeeping into one device's status."""
        entry = self._devices.get(device_id)
        if entry is None:
            return
        entry.processes = processes
        self._publish_device_changed(entry)

    def is_device_busy(self, device_id: str) -> bool:
        """Return whether a device is mid-operation (`streaming`/`starting`) and unsafe to flash."""
        entry = self._devices.get(device_id)
        return entry is not None and entry.state in ("streaming", "starting")

    async def ping_database(self) -> bool:
        """Return whether the persistence layer is currently reachable.

        `HealthService`'s composition-root signature was frozen without a
        direct `DeviceRepository`/session dependency of its own (main.py),
        so it calls this instead — a lightweight read through the repository
        this registry already holds, rather than a dedicated ping method the
        `DeviceRepository` Protocol does not define. `GET /api/health` maps a
        `False` result to HTTP 503 (architecture §7.1).
        """
        try:
            await self._device_repository.list_all()
        except Exception:
            return False
        return True

    # -- internal helpers -----------------------------------------------------

    def _apply_live_presence(self, entry: _DeviceEntry, event: DeviceArrived, now: int) -> None:
        """Refresh one entry's live USB fields from a settled arrival."""
        entry.present = True
        entry.usb_snapshot = event.snapshot
        entry.driver_conflict = event.driver_conflict
        entry.last_seen_at = now
        entry.last_topology_path = event.snapshot.topology_path
        entry.last_vendor_id = event.snapshot.vendor_id
        entry.last_product_id = event.snapshot.product_id
        entry.last_manufacturer = event.snapshot.manufacturer or ""
        entry.last_product = event.snapshot.product or ""
        entry.last_serial = event.snapshot.serial or ""

    def _find_entry_by_topology(self, topology_path: str) -> _DeviceEntry | None:
        """Find the currently-present entry occupying `topology_path`, if any."""
        for entry in self._devices.values():
            if entry.present and (
                (
                    entry.usb_snapshot is not None
                    and entry.usb_snapshot.topology_path == topology_path
                )
                or (entry.identity_kind == "usb" and entry.identity_key == topology_path)
            ):
                return entry
        return None

    def _entry_from_row(self, row: PersistedDeviceRow) -> _DeviceEntry:
        """Build a fresh, presence-absent in-memory entry from a persisted row."""
        state: DeviceState
        reason: str | None
        if row.enabled:
            state, reason = "configured", None
        else:
            state, reason = "stopped", "disabled"
        return _DeviceEntry(
            device_id=f"{row.identity_kind}:{row.identity_key}",
            record_id=row.id,
            identity_kind=row.identity_kind,
            identity_key=row.identity_key,
            needs_identification=False,
            name=row.name,
            description=row.description,
            notes=row.notes,
            antenna=row.antenna,
            output_port=row.output_port,
            enabled=row.enabled,
            visibility=row.visibility,
            center_hz=row.center_hz,
            sample_rate=row.sample_rate,
            gain_db=row.gain_db,
            gain_auto=row.gain_auto,
            ppm_correction=row.ppm_correction,
            bias_tee=row.bias_tee,
            direct_sampling=row.direct_sampling,
            present=False,
            state=state,
            state_since=self._clock.now_ms(),
            state_reason=reason,
            usb_snapshot=None,
            driver_conflict=False,
            last_topology_path=row.last_topology_path,
            last_vendor_id=row.last_vendor_id,
            last_product_id=row.last_product_id,
            last_manufacturer=row.last_manufacturer,
            last_product=row.last_product,
            last_serial=row.last_serial,
            last_seen_at=row.last_seen_at,
            pending_replug_until=row.pending_replug_until,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _set_state(self, entry: _DeviceEntry, new_state: DeviceState, reason: str | None) -> None:
        """Stamp a state transition's bookkeeping fields, without validating the transition."""
        entry.state = new_state
        entry.state_reason = reason
        entry.state_since = self._clock.now_ms()
        entry.updated_at = self._clock.now_ms()

    def _publish_device_changed(self, entry: _DeviceEntry) -> None:
        """Publish the public `device_changed` SSE event for one entry's current status."""
        self._event_bus.publish(
            SseMessage(event="device_changed", data=self._to_device_status(entry))
        )

    @staticmethod
    def _status_sort_key(entry: _DeviceEntry) -> tuple[int, str]:
        """Sort key matching architecture §7.2: by topology path, absent devices last."""
        if entry.present and entry.usb_snapshot is not None:
            return (0, entry.usb_snapshot.topology_path)
        return (1, entry.device_id)

    def _to_device_status(self, entry: _DeviceEntry) -> DeviceStatus:
        """Build the `GET /api/status` / SSE payload shape for one entry."""
        usb: UsbInfo | None = None
        usb_last_known: UsbLastKnownInfo | None = None
        if entry.present and entry.usb_snapshot is not None:
            snapshot = entry.usb_snapshot
            usb = UsbInfo(
                topology_path=snapshot.topology_path,
                bus_number=snapshot.bus_number,
                port_chain=snapshot.port_chain,
                hub_depth=max(len(snapshot.port_chain) - 1, 0),
                device_address=snapshot.device_address,
                vendor_id=snapshot.vendor_id,
                product_id=snapshot.product_id,
                manufacturer=snapshot.manufacturer,
                product=snapshot.product,
                serial=snapshot.serial,
                driver=snapshot.driver,
                driver_conflict=entry.driver_conflict,
            )
        elif entry.record_id is not None:
            usb_last_known = UsbLastKnownInfo(
                topology_path=entry.last_topology_path,
                vendor_id=entry.last_vendor_id,
                product_id=entry.last_product_id,
                manufacturer=entry.last_manufacturer or None,
                product=entry.last_product or None,
                serial=entry.last_serial or None,
            )

        output: OutputInfo | None = None
        if entry.output_port is not None:
            # `host` is deliberately left blank here — see this module's
            # docstring; the router must overlay the resolved advertised host.
            output = OutputInfo(
                host="", iq_port=entry.output_port, control_port=entry.output_port + 2
            )

        return DeviceStatus(
            device_id=entry.device_id,
            record_id=entry.record_id,
            identity_kind=entry.identity_kind,
            identity_key=entry.identity_key,
            needs_identification=entry.needs_identification,
            name=entry.name,
            description=entry.description,
            notes=entry.notes,
            antenna=entry.antenna,
            state=entry.state,
            state_since=entry.state_since,
            state_reason=entry.state_reason,
            present=entry.present,
            enabled=entry.enabled,
            visibility=entry.visibility,
            usb=usb,
            usb_last_known=usb_last_known,
            output=output,
            tuner=entry.tuner,
            processes=entry.processes,
            clients=None,
            last_seen_at=entry.last_seen_at,
        )

    def _to_device_record(self, entry: _DeviceEntry) -> DeviceRecord:
        """Build the `GET /api/devices` item / `PATCH` response shape for one entry."""
        return DeviceRecord(
            device_id=entry.device_id,
            record_id=entry.record_id,
            identity_kind=entry.identity_kind,
            identity_key=entry.identity_key,
            name=entry.name,
            description=entry.description,
            notes=entry.notes,
            antenna=entry.antenna,
            output_port=entry.output_port,
            control_port=(entry.output_port + 2) if entry.output_port is not None else None,
            enabled=entry.enabled,
            visibility=entry.visibility,
            center_hz=entry.center_hz,
            sample_rate=entry.sample_rate,
            gain_db=entry.gain_db,
            gain_auto=entry.gain_auto,
            ppm_correction=entry.ppm_correction,
            bias_tee=entry.bias_tee,
            direct_sampling=entry.direct_sampling,  # type: ignore[arg-type]
            present=entry.present,
            needs_identification=entry.needs_identification,
            state=entry.state,
            last_topology_path=entry.last_topology_path,
            last_serial=entry.last_serial,
            last_seen_at=entry.last_seen_at,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )


__all__ = [
    "DeviceNotFoundError",
    "DeviceRegistry",
    "DeviceUnidentifiedError",
    "IncompleteConfigurationError",
    "RunnableDevice",
]
