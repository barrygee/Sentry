"""Process lifecycle for every dongle's `rtl_tcp` + relay pair (architecture §4.3, §3.3).

For each enabled, present, configured device: resolve the librtlsdr index by
serial at spawn time (ADR-0003 — never cached), spawn `rtl_tcp` then the
relay, watch both, restart the pair on any exit with capped backoff, stop
pairs whose device left or was disabled, and reconcile the running set
against the desired set on every registry change. Never touches an IQ byte.

**Settle-to-streaming simplification.** Architecture §10 gates `starting ->
streaming` on *both* the 3 s settle window *and* `control_follower` receiving
one `state` event. Coupling this module tightly to `control_follower`'s
connection state would need a cross-service handshake with no clean seam yet
(control_follower is a fully independent, reconnect-tolerant NDJSON client);
this implementation settles on elapsed time alone and flags the simplification
here and in the Phase 2A handoff rather than silently dropping the coupling.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from dataclasses import dataclass, field
from typing import Literal

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.process import ManagedProcess, ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.schemas.device import ProcessInfo
from app.backend.schemas.events import NoticeItem
from app.backend.services.device_registry import DeviceRegistry, RunnableDevice
from app.backend.services.event_bus import EventBus, SseMessage

RESTART_BUDGET_MAX_RESTARTS = 5
RESTART_BUDGET_WINDOW_S = 120.0
"""5 restarts within 120s exhausts the budget → `error`, `crash_loop` (architecture §10)."""

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0
"""Exponential backoff caps at 60s and retries forever past the crash-loop threshold
(decision 7) rather than giving up, which is the right default for an unattended Pi."""

SETTLE_WINDOW_S = 3.0
"""Both PIDs must stay alive this long, with one control-follower state event, to reach
`streaming` (architecture §10)."""

WEDGE_EXIT_CODE = 75
"""The relay's `RELAY_WEDGE_EXIT_CODE` (architecture §2.1) — treated as an ordinary
crash-and-restart, but raises a `notice` specifically calling out the wedge recovery."""

IndexResolutionFailure = Literal["index_unresolved", "ambiguous_index", "driver_conflict"]


class IndexResolutionError(Exception):
    """Raised by `resolve_spawn_index` for any of the three documented failure modes."""

    def __init__(self, reason: IndexResolutionFailure, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ManagedPair:
    """One device's supervised `rtl_tcp` + relay processes and their bookkeeping."""

    device_id: str
    internal_port: int
    """The loopback `rtl_tcp` port: `SENTRY_INTERNAL_PORT_BASE + slot`."""

    rtl_tcp_pid: int | None
    relay_pid: int | None
    restarts: int
    last_restart_at: int | None
    last_exit_code: int | None


@dataclass(slots=True)
class _RunningPair:
    """Internal bookkeeping for one currently-spawned `rtl_tcp` + relay pair."""

    device_id: str
    internal_port: int
    rtl_tcp_process: ManagedProcess
    relay_process: ManagedProcess
    spawned_output_port: int
    spawned_ppm_correction: int
    watch_task: asyncio.Task[None] | None = None
    settle_task: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _RestartBookkeeping:
    """Per-device restart history, independent of any single `_RunningPair` instance."""

    restart_timestamps: list[float] = field(default_factory=list)
    backoff_s: float = BACKOFF_START_S
    restarts: int = 0
    last_restart_at: int | None = None
    last_exit_code: int | None = None


class SupervisorService:
    """Spawns, watches, restarts and stops every dongle's process pair."""

    def __init__(
        self,
        process_spawner: ProcessSpawner,
        rtlsdr_library: RtlSdrLibrary,
        device_registry: DeviceRegistry,
        clock: Clock,
        event_bus: EventBus,
        rtl_tcp_path: str,
        relay_path: str,
        internal_port_base: int,
        max_devices: int,
    ) -> None:
        self._process_spawner = process_spawner
        self._rtlsdr_library = rtlsdr_library
        self._device_registry = device_registry
        self._clock = clock
        self._event_bus = event_bus
        self._rtl_tcp_path = rtl_tcp_path
        self._relay_path = relay_path
        self._internal_port_base = internal_port_base
        self._max_devices = max_devices
        self._pairs: dict[str, _RunningPair] = {}
        self._internal_ports_by_device: dict[str, int] = {}
        self._restart_bookkeeping: dict[str, _RestartBookkeeping] = {}

    async def reconcile(self) -> None:
        """Bring the running set of pairs in line with the registry's desired set.

        Called on startup and after every registry change: spawns pairs for
        newly enabled+present+configured devices, stops pairs whose device
        left or was disabled, and leaves everything else untouched.
        """
        desired_by_id = {
            device.device_id: device for device in self._device_registry.list_runnable_devices()
        }

        for device_id in list(self._pairs):
            if device_id not in desired_by_id:
                await self._stop_pair(device_id, grace_period_s=5.0)

        for device_id, desired in desired_by_id.items():
            running_pair = self._pairs.get(device_id)
            if running_pair is not None and (
                running_pair.spawned_output_port != desired.output_port
                or running_pair.spawned_ppm_correction != desired.ppm_correction
            ):
                # architecture §7.5: output_port/ppm_correction changes restart the pair.
                await self._stop_pair(device_id, grace_period_s=5.0)
                running_pair = None
            if running_pair is None:
                await self._spawn_pair(device_id, desired)

    async def resolve_spawn_index(self, serial: str) -> int:
        """Resolve the librtlsdr `-d <index>` for `serial`, right now, never cached.

        Raises `IndexResolutionError` (never returns a best-guess index) for
        each of the three documented failure modes (architecture §5.3):
        `driver_conflict` (zero devices enumerated at all), `index_unresolved`
        (no index reports this serial), `ambiguous_index` (more than one does).
        """
        device_count = self._rtlsdr_library.device_count()
        if device_count == 0:
            raise IndexResolutionError(
                "driver_conflict",
                "librtlsdr enumerates zero devices; the DVB kernel driver may still be "
                "bound (blacklist dvb_usb_rtl28xxu and reboot) or librtlsdr is unavailable",
            )

        matching_indices = [
            index
            for index in range(device_count)
            if self._rtlsdr_library.usb_strings(index).serial == serial
        ]
        if not matching_indices:
            raise IndexResolutionError(
                "index_unresolved", f"no librtlsdr index currently reports serial {serial!r}"
            )
        if len(matching_indices) > 1:
            raise IndexResolutionError(
                "ambiguous_index",
                f"{len(matching_indices)} librtlsdr indices report serial {serial!r}; "
                "flash a unique serial to disambiguate",
            )
        return matching_indices[0]

    async def stop_all(self, grace_period_s: float = 5.0) -> None:
        """Terminate every pair, escalating to `kill()` after `grace_period_s`.

        Architecture §10: the shutdown transition, applied to every device.
        """
        for device_id in list(self._pairs):
            await self._stop_pair(device_id, grace_period_s)
            await self._device_registry.transition(device_id, "stopped", "shutting_down")

    def get_pair(self, device_id: str) -> ManagedPair | None:
        """Return the current process/lifecycle state for one device's pair, if running."""
        running_pair = self._pairs.get(device_id)
        if running_pair is None:
            return None
        stats = self._restart_bookkeeping.get(device_id, _RestartBookkeeping())
        return ManagedPair(
            device_id=device_id,
            internal_port=running_pair.internal_port,
            rtl_tcp_pid=running_pair.rtl_tcp_process.pid,
            relay_pid=running_pair.relay_process.pid,
            restarts=stats.restarts,
            last_restart_at=stats.last_restart_at,
            last_exit_code=stats.last_exit_code,
        )

    # -- spawn / restart / stop ------------------------------------------------

    async def _spawn_pair(self, device_id: str, desired: RunnableDevice) -> None:
        """Resolve the spawn index, spawn `rtl_tcp` then the relay, and start watching them."""
        try:
            resolved_index = await self.resolve_spawn_index(desired.serial)
        except IndexResolutionError as error:
            await self._device_registry.transition(device_id, "error", error.reason)
            self._publish_notice("error", error.reason, device_id, str(error))
            return

        internal_port = self._allocate_internal_port(device_id)
        if internal_port is None:
            await self._device_registry.transition(device_id, "error", "port_in_use")
            self._publish_notice(
                "error", "port_in_use", device_id, "no free internal loopback port available"
            )
            return

        rtl_tcp_argv = [
            self._rtl_tcp_path,
            "-a",
            "127.0.0.1",
            "-p",
            str(internal_port),
            "-d",
            str(resolved_index),
        ]
        if desired.ppm_correction:
            rtl_tcp_argv += ["-P", str(desired.ppm_correction)]

        try:
            rtl_tcp_process = await self._process_spawner.spawn(
                rtl_tcp_argv, {}, name=f"{device_id}-rtl_tcp"
            )
        except OSError as error:
            self._release_internal_port(device_id)
            await self._device_registry.transition(device_id, "error", "spawn_failed")
            self._publish_notice("error", "spawn_failed", device_id, str(error))
            return

        # Exactly these six env vars, and no others (architecture §12.7) —
        # everything else about the relay (protocol, defaults, tuning) is
        # frozen and configured entirely through them.
        relay_env = {
            "RELAY_UPSTREAM_HOST": "127.0.0.1",
            "RELAY_UPSTREAM_PORT": str(internal_port),
            "RELAY_LISTEN_HOST": "0.0.0.0",
            "RELAY_LISTEN_PORT": str(desired.output_port),
            "RELAY_CONTROL_PORT": str(desired.control_port),
            "RELAY_EXIT_ON_WEDGE": "1",
        }
        try:
            relay_process = await self._process_spawner.spawn(
                [sys.executable, self._relay_path], relay_env, name=f"{device_id}-relay"
            )
        except OSError as error:
            rtl_tcp_process.terminate()
            self._release_internal_port(device_id)
            await self._device_registry.transition(device_id, "error", "spawn_failed")
            self._publish_notice("error", "spawn_failed", device_id, str(error))
            return

        running_pair = _RunningPair(
            device_id=device_id,
            internal_port=internal_port,
            rtl_tcp_process=rtl_tcp_process,
            relay_process=relay_process,
            spawned_output_port=desired.output_port,
            spawned_ppm_correction=desired.ppm_correction,
        )
        self._pairs[device_id] = running_pair
        running_pair.watch_task = asyncio.create_task(
            self._watch_pair(device_id), name=f"supervisor-watch-{device_id}"
        )
        running_pair.settle_task = asyncio.create_task(
            self._settle_to_streaming(device_id), name=f"supervisor-settle-{device_id}"
        )

        await self._device_registry.transition(device_id, "starting", None)
        self._publish_process_info(device_id, running_pair)

    async def _settle_to_streaming(self, device_id: str) -> None:
        """Promote a `starting` pair to `streaming` once it survives the settle window."""
        try:
            await self._clock.sleep(SETTLE_WINDOW_S)
        except asyncio.CancelledError:
            return
        if device_id in self._pairs:
            await self._device_registry.transition(device_id, "streaming", None)
            self._restart_bookkeeping.setdefault(
                device_id, _RestartBookkeeping()
            ).backoff_s = BACKOFF_START_S

    async def _watch_pair(self, device_id: str) -> None:
        """Wait for either process in the pair to exit, then run the restart flow."""
        running_pair = self._pairs.get(device_id)
        if running_pair is None:
            return
        rtl_tcp_wait = asyncio.ensure_future(running_pair.rtl_tcp_process.wait())
        relay_wait = asyncio.ensure_future(running_pair.relay_process.wait())
        try:
            done, pending = await asyncio.wait(
                {rtl_tcp_wait, relay_wait}, return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            rtl_tcp_wait.cancel()
            relay_wait.cancel()
            return
        for pending_task in pending:
            pending_task.cancel()
        exit_code = next(iter(done)).result()
        await self._handle_pair_exit(device_id, exit_code)

    async def _handle_pair_exit(self, device_id: str, exit_code: int) -> None:
        """Reap the exited pair and restart it with capped backoff (architecture §10)."""
        running_pair = self._pairs.pop(device_id, None)
        if running_pair is None:
            return
        if running_pair.settle_task is not None:
            running_pair.settle_task.cancel()
        with contextlib.suppress(Exception):
            running_pair.rtl_tcp_process.terminate()
        with contextlib.suppress(Exception):
            running_pair.relay_process.terminate()
        self._release_internal_port(device_id)

        if exit_code == WEDGE_EXIT_CODE:
            self._publish_notice(
                "warn",
                "relay_wedge_exit",
                device_id,
                "relay exited on watchdog wedge detection (exit 75); respawning the pair",
            )

        stats = self._restart_bookkeeping.setdefault(device_id, _RestartBookkeeping())
        now_monotonic = self._clock.monotonic()
        stats.restart_timestamps = [
            timestamp
            for timestamp in stats.restart_timestamps
            if now_monotonic - timestamp < RESTART_BUDGET_WINDOW_S
        ]
        stats.restart_timestamps.append(now_monotonic)
        stats.restarts += 1
        stats.last_restart_at = self._clock.now_ms()
        stats.last_exit_code = exit_code
        over_budget = len(stats.restart_timestamps) > RESTART_BUDGET_MAX_RESTARTS

        if over_budget:
            await self._device_registry.transition(device_id, "error", "crash_loop")
            self._publish_notice(
                "error",
                "crash_loop",
                device_id,
                "restart budget exhausted (5 restarts within 120s); retrying with capped backoff",
            )
        else:
            await self._device_registry.transition(device_id, "starting", "restarting")

        backoff_s = stats.backoff_s
        try:
            await self._clock.sleep(backoff_s)
        except asyncio.CancelledError:
            return
        stats.backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)

        if over_budget:
            await self._device_registry.transition(device_id, "starting", "backoff_elapsed")

        desired = self._current_desired(device_id)
        if desired is not None:
            await self._spawn_pair(device_id, desired)

    async def _stop_pair(self, device_id: str, grace_period_s: float) -> None:
        """Stop one running pair: cancel its watchers, then terminate and kill after grace."""
        running_pair = self._pairs.pop(device_id, None)
        if running_pair is None:
            return
        if running_pair.watch_task is not None:
            running_pair.watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running_pair.watch_task
        if running_pair.settle_task is not None:
            running_pair.settle_task.cancel()

        running_pair.rtl_tcp_process.terminate()
        running_pair.relay_process.terminate()
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    running_pair.rtl_tcp_process.wait(), running_pair.relay_process.wait()
                ),
                timeout=grace_period_s,
            )
        except TimeoutError:
            running_pair.rtl_tcp_process.kill()
            running_pair.relay_process.kill()
        self._release_internal_port(device_id)
        self._restart_bookkeeping.pop(device_id, None)
        self._device_registry.update_process_info(device_id, None)

    # -- helpers ----------------------------------------------------------------

    def _current_desired(self, device_id: str) -> RunnableDevice | None:
        """Look up `device_id` in the registry's current desired set, if still present."""
        for device in self._device_registry.list_runnable_devices():
            if device.device_id == device_id:
                return device
        return None

    def _allocate_internal_port(self, device_id: str) -> int | None:
        """Assign the lowest free loopback port in the configured range to `device_id`."""
        used_ports = set(self._internal_ports_by_device.values())
        for candidate_port in range(
            self._internal_port_base, self._internal_port_base + self._max_devices
        ):
            if candidate_port not in used_ports:
                self._internal_ports_by_device[device_id] = candidate_port
                return candidate_port
        return None

    def _release_internal_port(self, device_id: str) -> None:
        """Free `device_id`'s loopback port slot, if it held one, for reuse by another device."""
        self._internal_ports_by_device.pop(device_id, None)

    def _publish_process_info(self, device_id: str, running_pair: _RunningPair) -> None:
        """Push current PID/port bookkeeping into the registry as `ProcessInfo`."""
        stats = self._restart_bookkeeping.get(device_id, _RestartBookkeeping())
        self._device_registry.update_process_info(
            device_id,
            ProcessInfo(
                rtl_tcp_pid=running_pair.rtl_tcp_process.pid,
                relay_pid=running_pair.relay_process.pid,
                internal_port=running_pair.internal_port,
                restarts=stats.restarts,
                last_restart_at=stats.last_restart_at,
                last_exit_code=stats.last_exit_code,
            ),
        )

    def _publish_notice(self, level: str, code: str, device_id: str, message: str) -> None:
        """Publish an operator-facing `notice` SSE event (architecture §7.3)."""
        self._event_bus.publish(
            SseMessage(
                event="notice",
                data=NoticeItem(
                    level=level,  # type: ignore[arg-type]
                    code=code,
                    message=message,
                    device_id=device_id,
                    ts=self._clock.now_ms(),
                ),
            )
        )
