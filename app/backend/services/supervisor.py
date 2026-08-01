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

**Per-device locking (correctness fix).** `reconcile()` is re-run on every
registry change from an independent background task, while a crashed pair's
restart-with-backoff runs from its own long-lived watch task — with no
coordination between them, both could independently decide "no pair is
running for this device, spawn one" for the *same* device_id at the same
time, producing multiple untracked orphaned pairs (reproduced: one crash of
one `rtl_tcp` yielding three spawned pairs, two of them never reachable
again by `stop_all()`). Every spawn/stop/reconcile decision for one
`device_id` is now made only while holding that device's `asyncio.Lock`
(`_lock_for`), and a device mid-restart-backoff is tracked in
`_pending_restart` so `reconcile()` never spawns a second pair for it while
the first restart is still pending. The task performing the backoff sleep is
also kept in `_watch_tasks` — which survives the pair being popped out of
`_pairs` — so `stop_all()` can find and cancel it instead of leaving it to
run past shutdown (architecture: no orphaned child process may survive
`docker stop`).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from dataclasses import dataclass, field
from typing import Literal

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.process import ManagedProcess, ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.schemas.device import ProcessInfo
from app.backend.schemas.events import NoticeItem
from app.backend.services.control_follower import ControlFollowerService
from app.backend.services.device_registry import DeviceRegistry, RunnableDevice
from app.backend.services.event_bus import EventBus, SseMessage

CONTROL_FOLLOWER_HOST = "127.0.0.1"
"""The relay's control port is bound on every interface (`0.0.0.0`), but the
supervisor and its in-process control follower always run alongside it on the
same host, so the follower connects over loopback rather than the public
address."""

_FALLBACK_SPAWN_PATH = "/usr/local/bin:/usr/bin:/bin"
"""Used only when the parent process itself has no `PATH` in its environment
(e.g. a minimal test harness) — the real runtime image always inherits one."""

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
    """Internal bookkeeping for one currently-spawned `rtl_tcp` + relay pair.

    Does **not** hold the watch task — that lives in `SupervisorService.
    _watch_tasks`, keyed by `device_id`, specifically so it survives this
    dataclass instance being popped out of `_pairs` on exit and remains
    reachable (and cancellable) for the whole duration of a restart backoff.
    """

    device_id: str
    internal_port: int
    rtl_tcp_process: ManagedProcess
    relay_process: ManagedProcess
    spawned_output_port: int
    spawned_ppm_correction: int
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
        control_follower: ControlFollowerService,
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
        self._control_follower = control_follower
        self._pairs: dict[str, _RunningPair] = {}
        self._internal_ports_by_device: dict[str, int] = {}
        self._restart_bookkeeping: dict[str, _RestartBookkeeping] = {}
        self._watch_tasks: dict[str, asyncio.Task[None]] = {}
        """The task running `_watch_pair` (which, on exit, runs `_handle_pair_exit`
        inline, including its backoff sleep) for `device_id`. Populated at
        spawn time and only removed by `_stop_pair` — unlike `_pairs`, this
        dict's entry survives the pair itself exiting, so a task asleep in
        backoff remains reachable for `stop_all()` to cancel."""
        self._pending_restart: set[str] = set()
        """`device_id`s currently between an exited pair and its scripted
        restart (i.e. asleep in `_handle_pair_exit`'s backoff). `reconcile()`
        must never spawn a second pair for one of these — that double-spawn,
        racing the scripted restart, is exactly how one crash used to produce
        three untracked pairs."""
        self._device_locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, device_id: str) -> asyncio.Lock:
        """Return `device_id`'s spawn/stop/reconcile lock, creating it on first use."""
        lock = self._device_locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._device_locks[device_id] = lock
        return lock

    async def reconcile(self) -> None:
        """Bring the running set of pairs in line with the registry's desired set.

        Called on startup and after every registry change: spawns pairs for
        newly enabled+present+configured devices, stops pairs whose device
        left or was disabled, and leaves everything else untouched. Every
        per-device decision is made under that device's lock so this can
        never race a concurrent `_handle_pair_exit` restart for the same
        device (see this module's docstring).
        """
        desired_by_id = {
            device.device_id: device for device in self._device_registry.list_runnable_devices()
        }

        # Devices with a running pair *or* a restart pending in backoff both
        # need to be considered for "did this device leave the desired set" —
        # a device disabled/removed mid-backoff would otherwise never be
        # noticed here (it has no entry in `_pairs` to iterate) and would sit
        # in backoff until its watch task itself re-checks the desired set.
        for device_id in list(set(self._pairs) | self._pending_restart):
            if device_id not in desired_by_id:
                async with self._lock_for(device_id):
                    await self._stop_pair(
                        device_id, grace_period_s=5.0, reason=self._departure_reason(device_id)
                    )

        for device_id, desired in desired_by_id.items():
            async with self._lock_for(device_id):
                running_pair = self._pairs.get(device_id)
                if running_pair is not None and (
                    running_pair.spawned_output_port != desired.output_port
                    or running_pair.spawned_ppm_correction != desired.ppm_correction
                ):
                    # architecture §7.5: output_port/ppm_correction changes restart the pair.
                    await self._stop_pair(device_id, grace_period_s=5.0, reason="reconfiguring")
                    running_pair = None
                if running_pair is None and device_id not in self._pending_restart:
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
        Also cancels any watch task still asleep in a restart backoff — that
        task is not in `_pairs` (its pair already exited) but remains in
        `_watch_tasks` for exactly this reason, so lifespan shutdown can
        reap it instead of leaving it to spawn a new `rtl_tcp`/relay pair
        after the process is supposed to have already exited.
        """
        for device_id in list(set(self._pairs) | set(self._watch_tasks)):
            async with self._lock_for(device_id):
                await self._stop_pair(device_id, grace_period_s, reason="shutting_down")

    async def stop_device(self, device_id: str, reason: str) -> None:
        """Stop one device's pair (and any pending restart backoff) immediately, if any.

        Public, unlike `_stop_pair`, so `EepromService` can guarantee
        `rtl_tcp` has actually released the USB device before `rtl_eeprom`
        opens it — taking this device's own lock exactly like
        `reconcile()`/`stop_all()` do, so a flash can never race a
        concurrently-spawning pair for the same `device_id`. A no-op if
        nothing is running or backing off for this device.
        """
        async with self._lock_for(device_id):
            await self._stop_pair(device_id, grace_period_s=5.0, reason=reason)

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
        # Startup tuning (architecture §7.5) — previously built into
        # `RunnableDevice` but never read here, so a `PATCH` setting
        # `center_hz`/`sample_rate`/`gain_db`/`gain_auto` reached no hardware
        # at all. `gain_db` is only passed when AGC is off: rtl_tcp treats an
        # omitted `-g` as "use automatic gain control", so passing a stale
        # `gain_db` while `gain_auto` is true would silently fight the
        # operator's own AGC choice.
        if desired.center_hz is not None:
            rtl_tcp_argv += ["-f", str(desired.center_hz)]
        if desired.sample_rate is not None:
            rtl_tcp_argv += ["-s", str(desired.sample_rate)]
        if not desired.gain_auto and desired.gain_db is not None:
            rtl_tcp_argv += ["-g", str(desired.gain_db)]

        try:
            rtl_tcp_process = await self._process_spawner.spawn(
                rtl_tcp_argv, self._rtl_tcp_env(), name=f"{device_id}-rtl_tcp"
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
        self._watch_tasks[device_id] = asyncio.create_task(
            self._watch_pair(device_id), name=f"supervisor-watch-{device_id}"
        )
        running_pair.settle_task = asyncio.create_task(
            self._settle_to_streaming(device_id), name=f"supervisor-settle-{device_id}"
        )
        # Read-mostly NDJSON follower on the relay's just-spawned control
        # port, so live tuner state (including this operator's own tuning
        # request) is mirrored back into `DeviceStatus.tuner` — previously
        # never started anywhere, so `tuner` stayed permanently null.
        await self._control_follower.start_following(
            device_id, CONTROL_FOLLOWER_HOST, desired.control_port
        )

        await self._device_registry.transition(device_id, "starting", None)
        self._publish_process_info(device_id, running_pair)

    def _rtl_tcp_env(self) -> dict[str, str]:
        """Build `rtl_tcp`'s spawn environment: just enough `PATH` to resolve the binary.

        The previous `env={}` made `create_subprocess_exec` resolve a bare
        `rtl_tcp` (the configured default) against the *child's* PATH, which
        with a completely empty environment falls back to `/bin:/usr/bin` —
        `rtl_tcp` lives in `/usr/local/bin` in the runtime image, so every
        spawn failed `FileNotFoundError` (`spawn_failed`) and no dongle could
        ever stream in the container. Deliberately just `PATH`, not a copy of
        the whole parent environment, to keep the child's environment as
        narrow as the relay's own six-variable invariant (module docstring).
        """
        return {"PATH": os.environ.get("PATH", _FALLBACK_SPAWN_PATH)}

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
        """Reap the exited pair and restart it with capped backoff (architecture §10).

        Runs as (the tail of) `self._watch_tasks[device_id]` — that task
        stays registered there for this entire method's duration, including
        the backoff sleep, so `stop_all()`/`reconcile()` can always find and
        cancel it. `device_id` is added to `_pending_restart` for the same
        span so `reconcile()` never spawns a second, competing pair while
        this one is merely asleep waiting to respawn.
        """
        # No `await` occurs between the pop and the `_pending_restart.add()`
        # below, so this whole reaping step is atomic with respect to every
        # other coroutine (asyncio only switches tasks at an `await`) —
        # `reconcile()` can never observe "no pair, not yet pending_restart"
        # for this device_id.
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
        self._pending_restart.add(device_id)

        try:
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
                    "restart budget exhausted (5 restarts within 120s); retrying with capped "
                    "backoff",
                )
            else:
                await self._device_registry.transition(device_id, "starting", "restarting")

            backoff_s = stats.backoff_s
            try:
                await self._clock.sleep(backoff_s)
            except asyncio.CancelledError:
                # Cancelled by `_stop_pair` (device disabled/removed, or
                # process shutdown) — the caller already owns this device's
                # lock and is about to (or already did) clean up `_pairs`/
                # `_watch_tasks`/registry state itself; nothing left to do.
                return
            stats.backoff_s = min(backoff_s * 2, BACKOFF_MAX_S)

            if over_budget:
                await self._device_registry.transition(device_id, "starting", "backoff_elapsed")

            async with self._lock_for(device_id):
                desired = self._current_desired(device_id)
                if desired is not None:
                    await self._spawn_pair(device_id, desired)
                else:
                    # The device left the desired set (disabled/unplugged)
                    # while this backoff was asleep. Previously this branch
                    # did not exist at all: the entry was transitioned to
                    # `starting` above and then simply abandoned — with no
                    # pair, no watcher, and (`starting` being absent from
                    # `_STATES_READY_FOR_RECONCILE`) no way for even a
                    # replug to clear it. `_stop_pair` recognises this task
                    # as its own current task and skips self-cancellation,
                    # but still performs every other cleanup step and settles
                    # the device to `stopped`.
                    await self._stop_pair(
                        device_id, grace_period_s=5.0, reason=self._departure_reason(device_id)
                    )
        finally:
            self._pending_restart.discard(device_id)

    async def _stop_pair(self, device_id: str, grace_period_s: float, reason: str) -> None:
        """Stop one running pair (or a still-backing-off restart) and settle it to `stopped`.

        Callers hold `device_id`'s lock (`_lock_for`) for the duration of
        this call — never call this directly. `reason` is stamped as the
        device's `state_reason` once it reaches `stopped`, so a disabled
        device now actually surfaces as stopped (previously `_stop_pair`
        never touched the registry's state machine at all, leaving a
        just-disabled streaming device stuck reporting `state: streaming`
        forever, with `is_device_busy()` then refusing an EEPROM flash with
        advice — "disable it" — that had already been followed).
        """
        watch_task = self._watch_tasks.pop(device_id, None)
        if watch_task is not None and watch_task is not asyncio.current_task():
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task

        await self._control_follower.stop_following(device_id)

        running_pair = self._pairs.pop(device_id, None)
        if running_pair is not None:
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
        await self._device_registry.transition(device_id, "stopped", reason)

    def _departure_reason(self, device_id: str) -> str:
        """Return why `device_id` left the desired set: `disabled` or `device_absent`.

        Mirrors `DeviceRegistry.apply_device_departed`'s own reasoning so a
        pair stopped because its device left the desired set reports the
        same `state_reason` regardless of which code path noticed first.
        """
        status = self._device_registry.get_status(device_id)
        if status is not None and not status.enabled:
            return "disabled"
        return "device_absent"

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
