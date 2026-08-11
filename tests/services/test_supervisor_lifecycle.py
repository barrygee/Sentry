"""Tests for the supervisor's process lifecycle: `_spawn_pair` and `_handle_pair_exit`.

`test_supervisor.py` covers index resolution and the *spawn-failure* backoff —
the paths where no process ever starts. This file covers what happens once one
does: spawning the pair, watching it exit, and restarting it under a budget.
That is where the crash-loop behaviour lives, and it was untested.

Every failure mode asserted here was a real one. The supervisor's own comments
record them: an `rtl_tcp` that exits within a second still holding nothing
(`device_busy`, distinct from a wedge); a relay whose spawn fails leaving a
live `rtl_tcp` claiming the USB interface into the next attempt; a pair whose
device is unplugged mid-backoff and was previously transitioned to `starting`
and then abandoned with no pair, no watcher, and no way back.

The clock is fake throughout, so the backoff schedule and the 120s restart
window are asserted exactly rather than slept through.

Run with:  uv run pytest tests/services/test_supervisor_lifecycle.py
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from app.backend.interfaces.process import ManagedProcess, ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.schemas.device import DeviceState, DeviceStatus, ProcessInfo
from app.backend.services.control_follower import ControlFollowerService
from app.backend.services.device_registry import DeviceRegistry, RunnableDevice
from app.backend.services.event_bus import EventBus
from app.backend.services.supervisor import (
    BACKOFF_MAX_S,
    BACKOFF_START_S,
    RESTART_BUDGET_MAX_RESTARTS,
    RESTART_BUDGET_WINDOW_S,
    WEDGE_EXIT_CODE,
    SupervisorService,
    _RestartBookkeeping,
)

from ..fakes.clock import FakeClock
from .test_supervisor import (
    INTERNAL_PORT_BASE,
    MAX_DEVICES,
    FakeRtlSdrLibrary,
    usb_strings,
)

DEVICE_ID = "dongle-a"
SERIAL = "AIS-01"


class FakeManagedProcess:
    """A `ManagedProcess` whose exit is driven by the test, not by an OS.

    `wait()` blocks on an `asyncio.Event` so a test can hold a pair "running"
    for as long as it needs and then exit it deliberately. `terminate`/`kill`
    are recorded rather than simulated: what the supervisor must do is send
    them, and whether it *waited* for the reap is visible in `killed`.
    """

    def __init__(self, pid: int, *, stderr: bytes = b"", exits_immediately_with: int | None = None):
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.resumed = False
        self._stderr = stderr
        self._exit_event = asyncio.Event()
        self._returncode: int | None = None
        if exits_immediately_with is not None:
            self.exit_with(exits_immediately_with)

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def exit_with(self, code: int) -> None:
        """Make the process report `code` and release anything awaiting `wait()`."""
        self._returncode = code
        self._exit_event.set()

    async def wait(self) -> int:
        await self._exit_event.wait()
        assert self._returncode is not None
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        # A terminated process is a reaped one: without this, `_stop_process`'s
        # confirmation wait would block forever against a fake that never dies.
        self.exit_with(self._returncode if self._returncode is not None else -15)

    def kill(self) -> None:
        self.killed = True
        self.exit_with(self._returncode if self._returncode is not None else -9)

    def resume(self) -> None:
        self.resumed = True

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", self._stderr)


class FakeProcessSpawner:
    """Hands out `FakeManagedProcess`es and records every spawn request.

    Scriptable per call index so a test can fail the *relay* spawn while the
    `rtl_tcp` one succeeds — the ordering that leaves a live process holding
    the USB interface, and the reason that branch exists at all.
    """

    def __init__(
        self,
        *,
        fail_spawn_names: frozenset[str] = frozenset(),
        immediate_exit_names: frozenset[str] = frozenset(),
        stderr_by_name: dict[str, bytes] | None = None,
    ) -> None:
        self._fail_spawn_names = fail_spawn_names
        self._immediate_exit_names = immediate_exit_names
        self._stderr_by_name = stderr_by_name or {}
        self.spawns: list[tuple[list[str], dict[str, str], str]] = []
        self.processes_by_name: dict[str, FakeManagedProcess] = {}
        self._next_pid = 1000

    async def spawn(
        self,
        argv: list[str],
        env: dict[str, str],
        name: str,
        capture_output: bool = False,
    ) -> ManagedProcess:
        self.spawns.append((list(argv), dict(env), name))
        if name in self._fail_spawn_names:
            raise OSError(f"cannot spawn {name}")
        self._next_pid += 1
        process = FakeManagedProcess(
            self._next_pid,
            stderr=self._stderr_by_name.get(name, b""),
            exits_immediately_with=1 if name in self._immediate_exit_names else None,
        )
        self.processes_by_name[name] = process
        return process

    def spawned_names(self) -> list[str]:
        return [name for _, _, name in self.spawns]


class FakeControlFollower:
    """Records which device/port the supervisor asked it to follow."""

    def __init__(self) -> None:
        self.following: list[tuple[str, str, int]] = []
        self.stopped: list[str] = []

    async def start_following(self, device_id: str, host: str, control_port: int) -> None:
        self.following.append((device_id, host, control_port))

    async def stop_following(self, device_id: str) -> None:
        self.stopped.append(device_id)


class ScriptedDeviceRegistry:
    """A registry with a mutable desired set, so a device can leave mid-backoff."""

    def __init__(
        self,
        *,
        runnable: tuple[RunnableDevice, ...] = (),
        enabled: bool = True,
    ) -> None:
        self.runnable = runnable
        self.enabled = enabled
        self.transitions: list[tuple[str, DeviceState, str | None]] = []
        self.process_info: list[tuple[str, ProcessInfo | None]] = []

    def list_runnable_devices(self) -> tuple[RunnableDevice, ...]:
        return self.runnable

    def get_status(self, device_id: str) -> object | None:
        # Only `.enabled` is read, by `_departure_reason`.
        return cast(DeviceStatus, _Status(self.enabled))

    def update_process_info(self, device_id: str, processes: ProcessInfo | None) -> None:
        self.process_info.append((device_id, processes))

    async def transition(self, device_id: str, new_state: DeviceState, reason: str | None) -> None:
        self.transitions.append((device_id, new_state, reason))

    def reasons_for(self, state: DeviceState) -> list[str | None]:
        return [reason for _, seen_state, reason in self.transitions if seen_state == state]


class _Status:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled


def runnable_device(
    *,
    ppm_correction: int = 0,
    center_hz: int | None = None,
    sample_rate: int | None = None,
    gain_db: float | None = None,
    gain_auto: bool = True,
) -> RunnableDevice:
    return RunnableDevice(
        device_id=DEVICE_ID,
        record_id=1,
        serial=SERIAL,
        output_port=2345,
        control_port=2347,
        ppm_correction=ppm_correction,
        center_hz=center_hz,
        sample_rate=sample_rate,
        gain_db=gain_db,
        gain_auto=gain_auto,
    )


def build_supervisor(
    *,
    spawner: FakeProcessSpawner | None = None,
    registry: ScriptedDeviceRegistry | None = None,
    clock: FakeClock | None = None,
    follower: FakeControlFollower | None = None,
    library: FakeRtlSdrLibrary | None = None,
    max_devices: int = MAX_DEVICES,
) -> SupervisorService:
    the_clock = clock or FakeClock()
    return SupervisorService(
        process_spawner=cast(ProcessSpawner, spawner or FakeProcessSpawner()),
        rtlsdr_library=cast(
            RtlSdrLibrary,
            library or FakeRtlSdrLibrary(usb_strings_by_index={0: usb_strings(SERIAL)}),
        ),
        device_registry=cast(DeviceRegistry, registry or ScriptedDeviceRegistry()),
        clock=the_clock,
        event_bus=EventBus(clock=the_clock),
        rtl_tcp_path="/usr/bin/rtl_tcp",
        relay_path="/app/app/backend/relay/rtl_tcp_relay.py",
        internal_port_base=INTERNAL_PORT_BASE,
        max_devices=max_devices,
        control_follower=cast(ControlFollowerService, follower or FakeControlFollower()),
    )


async def settle() -> None:
    """Give spawned watch/settle tasks a few turns to reach their first await."""
    for _ in range(10):
        await asyncio.sleep(0)


async def cancel_background_tasks(supervisor: SupervisorService) -> None:
    """Cancel the watch/settle tasks a spawn leaves running, so no test leaks one."""
    for task in list(supervisor._watch_tasks.values()):  # noqa: SLF001 - test teardown
        task.cancel()
    for pair in list(supervisor._pairs.values()):  # noqa: SLF001 - test teardown
        if pair.settle_task is not None:
            pair.settle_task.cancel()
    await settle()


# ── _spawn_pair ───────────────────────────────────────────────────────────────


class TestSpawnPair:
    @pytest.mark.asyncio
    async def test_spawns_rtl_tcp_then_the_relay_and_starts_watching(self) -> None:
        """The happy path, and the ordering: `rtl_tcp` must exist before the relay dials it."""
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry()
        follower = FakeControlFollower()
        supervisor = build_supervisor(spawner=spawner, registry=registry, follower=follower)

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001
        await settle()

        assert spawner.spawned_names() == [f"{DEVICE_ID}-rtl_tcp", f"{DEVICE_ID}-relay"]
        assert supervisor.get_pair(DEVICE_ID) is not None
        assert (DEVICE_ID, "starting", None) in registry.transitions
        assert follower.following == [(DEVICE_ID, "127.0.0.1", 2347)]

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_rtl_tcp_is_bound_to_loopback_on_its_allocated_port(self) -> None:
        """The internal port is loopback-only: it is the relay's upstream, not a public one."""
        spawner = FakeProcessSpawner()
        supervisor = build_supervisor(spawner=spawner)

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001
        await settle()

        rtl_tcp_argv = spawner.spawns[0][0]
        assert rtl_tcp_argv[:7] == [
            "/usr/bin/rtl_tcp",
            "-a",
            "127.0.0.1",
            "-p",
            str(INTERNAL_PORT_BASE),
            "-d",
            "0",
        ]

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_tuning_arguments_reach_rtl_tcp(self) -> None:
        """These were built into `RunnableDevice` but never read — a PATCH reached no hardware."""
        spawner = FakeProcessSpawner()
        supervisor = build_supervisor(spawner=spawner)

        await supervisor._spawn_pair(  # noqa: SLF001
            DEVICE_ID,
            runnable_device(
                ppm_correction=12,
                center_hz=1_090_000_000,
                sample_rate=2_048_000,
                gain_db=28.0,
                gain_auto=False,
            ),
        )
        await settle()

        rtl_tcp_argv = spawner.spawns[0][0]
        assert rtl_tcp_argv[7:] == [
            "-P",
            "12",
            "-f",
            "1090000000",
            "-s",
            "2048000",
            "-g",
            "28.0",
        ]

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_gain_is_omitted_while_agc_is_on(self) -> None:
        """`rtl_tcp` reads an absent `-g` as "use AGC" — passing a stale gain would fight it."""
        spawner = FakeProcessSpawner()
        supervisor = build_supervisor(spawner=spawner)

        await supervisor._spawn_pair(  # noqa: SLF001
            DEVICE_ID, runnable_device(gain_db=28.0, gain_auto=True)
        )
        await settle()

        assert "-g" not in spawner.spawns[0][0]

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_the_relay_gets_exactly_its_six_frozen_env_vars(self) -> None:
        """Architecture §12.7: the relay is configured through these and nothing else."""
        spawner = FakeProcessSpawner()
        supervisor = build_supervisor(spawner=spawner)

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001
        await settle()

        _, relay_env, _ = spawner.spawns[1]
        assert relay_env == {
            "RELAY_UPSTREAM_HOST": "127.0.0.1",
            "RELAY_UPSTREAM_PORT": str(INTERNAL_PORT_BASE),
            "RELAY_LISTEN_HOST": "0.0.0.0",
            "RELAY_LISTEN_PORT": "2345",
            "RELAY_CONTROL_PORT": "2347",
            "RELAY_EXIT_ON_WEDGE": "1",
        }

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_an_unresolvable_index_records_a_failure_and_spawns_nothing(self) -> None:
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry()
        supervisor = build_supervisor(
            spawner=spawner,
            registry=registry,
            library=FakeRtlSdrLibrary(usb_strings_by_index={0: usb_strings("SOMEONE-ELSE")}),
        )

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001

        assert spawner.spawns == []
        assert registry.reasons_for("error") == ["index_unresolved"]

    @pytest.mark.asyncio
    async def test_an_unexpected_resolver_error_still_lands_the_device_in_error(self) -> None:
        """The broad `except` exists because a device stuck silently at `configured` was real.

        A bare `OSError` out of a ctypes call is not an `IndexResolutionError`,
        and before the catch-all it left the device present, enabled, and
        showing `0/N streaming` with nothing to explain why.
        """

        class ExplodingLibrary(FakeRtlSdrLibrary):
            def device_count(self) -> int:
                raise OSError("ctypes went sideways")

        registry = ScriptedDeviceRegistry()
        supervisor = build_supervisor(registry=registry, library=ExplodingLibrary())

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001

        assert registry.reasons_for("error") == ["spawn_failed"]

    @pytest.mark.asyncio
    async def test_a_full_port_range_is_reported_rather_than_overlapping(self) -> None:
        """Two pairs on one loopback port would silently cross their IQ streams."""
        registry = ScriptedDeviceRegistry()
        supervisor = build_supervisor(registry=registry, max_devices=1)
        supervisor._internal_ports_by_device["other"] = INTERNAL_PORT_BASE  # noqa: SLF001

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001

        assert registry.reasons_for("error") == ["port_in_use"]

    @pytest.mark.asyncio
    async def test_a_failed_rtl_tcp_spawn_releases_the_port_it_reserved(self) -> None:
        """A leaked reservation would shrink the usable range with every failed attempt."""
        spawner = FakeProcessSpawner(fail_spawn_names=frozenset({f"{DEVICE_ID}-rtl_tcp"}))
        registry = ScriptedDeviceRegistry()
        supervisor = build_supervisor(spawner=spawner, registry=registry)

        await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001

        assert registry.reasons_for("error") == ["spawn_failed"]
        assert supervisor._internal_ports_by_device == {}  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_an_rtl_tcp_that_dies_instantly_is_device_busy_not_a_wedge(self) -> None:
        """Hardware finding: `usb_claim_interface error -6` exits in well under a second.

        It streamed nothing, so it must never be funnelled into wedge-and-respawn.
        The relay must not be spawned to dial an upstream that is already gone.
        """
        spawner = FakeProcessSpawner(
            immediate_exit_names=frozenset({f"{DEVICE_ID}-rtl_tcp"}),
            stderr_by_name={f"{DEVICE_ID}-rtl_tcp": b"usb_claim_interface error -6\n"},
        )
        registry = ScriptedDeviceRegistry()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)

        spawn = asyncio.create_task(supervisor._spawn_pair(DEVICE_ID, runnable_device()))  # noqa: SLF001
        await settle()
        clock.advance(2.0)
        await spawn

        assert spawner.spawned_names() == [f"{DEVICE_ID}-rtl_tcp"]
        assert registry.reasons_for("error") == ["device_busy"]
        assert supervisor._internal_ports_by_device == {}  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_a_failed_relay_spawn_confirms_rtl_tcp_is_gone_first(self) -> None:
        """Otherwise it keeps the USB interface claimed straight into the next attempt.

        This is the wedge-recovery failure mode the module docstring records:
        a respawned `rtl_tcp` racing, and losing to, a still-alive predecessor.
        """
        spawner = FakeProcessSpawner(fail_spawn_names=frozenset({f"{DEVICE_ID}-relay"}))
        registry = ScriptedDeviceRegistry()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)

        spawn = asyncio.create_task(supervisor._spawn_pair(DEVICE_ID, runnable_device()))  # noqa: SLF001
        await settle()
        clock.advance(IMMEDIATE_EXIT_PROBE_SECONDS)
        await settle()
        await spawn

        rtl_tcp = spawner.processes_by_name[f"{DEVICE_ID}-rtl_tcp"]
        assert rtl_tcp.terminated or rtl_tcp.killed, "rtl_tcp was left holding the USB interface"
        assert registry.reasons_for("error") == ["spawn_failed"]
        assert supervisor._internal_ports_by_device == {}  # noqa: SLF001


IMMEDIATE_EXIT_PROBE_SECONDS = 2.0
"""Enough to clear `IMMEDIATE_EXIT_PROBE_S` on the fake clock."""


# ── _handle_pair_exit ─────────────────────────────────────────────────────────


async def spawn_running_pair(
    supervisor: SupervisorService, spawner: FakeProcessSpawner
) -> tuple[FakeManagedProcess, FakeManagedProcess]:
    """Spawn a pair and return its two processes, both still 'running'."""
    await supervisor._spawn_pair(DEVICE_ID, runnable_device())  # noqa: SLF001
    await settle()
    return (
        spawner.processes_by_name[f"{DEVICE_ID}-rtl_tcp"],
        spawner.processes_by_name[f"{DEVICE_ID}-relay"],
    )


class TestHandlePairExit:
    @pytest.mark.asyncio
    async def test_a_second_exit_for_the_same_pair_is_a_no_op(self) -> None:
        """Both processes exit together on a crash; only the first may drive a restart.

        Without the `None` guard the second would run the whole restart flow
        again against an already-reaped pair — double-counting the budget and
        racing a spawn that is already scheduled.
        """
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry()
        supervisor = build_supervisor(spawner=spawner, registry=registry)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        supervisor._pairs.pop(DEVICE_ID, None)  # noqa: SLF001
        transitions_before = len(registry.transitions)

        await supervisor._handle_pair_exit(DEVICE_ID, 1)  # noqa: SLF001

        assert len(registry.transitions) == transitions_before

    @pytest.mark.asyncio
    async def test_the_exited_pair_releases_its_port_before_any_respawn(self) -> None:
        """Held across the backoff, the respawn would find its own port in use."""
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()

        assert supervisor._internal_ports_by_device == {}  # noqa: SLF001
        assert DEVICE_ID in supervisor._pending_restart  # noqa: SLF001

        handling.cancel()
        await settle()

    @pytest.mark.asyncio
    async def test_both_processes_are_killed_before_the_device_is_eligible_to_respawn(
        self,
    ) -> None:
        """One exited; the other may be hung or SIGSTOPped and will ignore a polite SIGTERM.

        Escalating to SIGKILL and confirming the reap here is what actually
        frees the USB interface before the respawn races it.
        """
        spawner = FakeProcessSpawner()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, clock=clock)
        rtl_tcp, relay = await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        rtl_tcp.exit_with(1)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()

        assert relay.killed, "the surviving sibling was not escalated to SIGKILL"

        handling.cancel()
        await settle()

    @pytest.mark.asyncio
    async def test_a_wedge_exit_is_called_out_by_name(self) -> None:
        """Exit 75 restarts like any crash, but the operator must see it was a wedge."""
        spawner = FakeProcessSpawner()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        published: list[str] = []
        supervisor._publish_notice = (  # type: ignore[method-assign]  # noqa: SLF001
            lambda level, code, device_id, message: published.append(code)
        )

        handling = asyncio.create_task(  # noqa: SLF001
            supervisor._handle_pair_exit(DEVICE_ID, WEDGE_EXIT_CODE)
        )
        await settle()

        assert published == ["relay_wedge_exit"]

        handling.cancel()
        await settle()

    @pytest.mark.asyncio
    async def test_an_ordinary_crash_raises_no_wedge_notice(self) -> None:
        """The counterpart: exit 1 must not be described as a wedge recovery."""
        spawner = FakeProcessSpawner()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        published: list[str] = []
        supervisor._publish_notice = (  # type: ignore[method-assign]  # noqa: SLF001
            lambda level, code, device_id, message: published.append(code)
        )

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()

        assert published == []

        handling.cancel()
        await settle()

    @pytest.mark.asyncio
    async def test_the_backoff_doubles_after_each_handled_exit(self) -> None:
        """Driven through `_handle_pair_exit`, not by re-implementing the arithmetic.

        The doubling happens only *after* the sleep returns, so a test that
        cancelled the task mid-backoff would see an unchanged value and prove
        nothing. The device must stay in the desired set too: the departure
        branch runs `_stop_pair`, which discards this bookkeeping entirely.

        The clock is advanced only as far as the respawn needs. `SETTLE_WINDOW_S`
        is deliberately not reached — `_settle_to_streaming` resets the backoff
        to its starting value, which would erase exactly what is asserted here.
        """
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry(runnable=(runnable_device(),))
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()
        clock.advance(BACKOFF_START_S)
        await settle()
        clock.advance(IMMEDIATE_EXIT_PROBE_SECONDS)
        await settle()
        await handling

        assert supervisor._restart_bookkeeping[DEVICE_ID].backoff_s == BACKOFF_START_S * 2  # noqa: SLF001

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_the_backoff_stops_doubling_at_the_ceiling(self) -> None:
        """It retries forever past the cap rather than giving up — right for an unattended Pi."""
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry(runnable=(runnable_device(),))
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        stats = _RestartBookkeeping()
        stats.backoff_s = BACKOFF_MAX_S
        supervisor._restart_bookkeeping[DEVICE_ID] = stats  # noqa: SLF001
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()
        clock.advance(BACKOFF_MAX_S)
        await settle()
        clock.advance(IMMEDIATE_EXIT_PROBE_SECONDS)
        await settle()
        await handling

        assert supervisor._restart_bookkeeping[DEVICE_ID].backoff_s == BACKOFF_MAX_S  # noqa: SLF001

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_exhausting_the_restart_budget_reports_a_crash_loop(self) -> None:
        """Six restarts inside the 120s window is the threshold (architecture §10)."""
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        stats = _RestartBookkeeping()
        # One short of the budget, all inside the window.
        stats.restart_timestamps = [clock.monotonic()] * RESTART_BUDGET_MAX_RESTARTS
        supervisor._restart_bookkeeping[DEVICE_ID] = stats  # noqa: SLF001
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()

        assert (DEVICE_ID, "error", "crash_loop") in registry.transitions

        handling.cancel()
        await settle()

    @pytest.mark.asyncio
    async def test_restarts_older_than_the_window_do_not_count_toward_the_budget(self) -> None:
        """A device that crashes once a day is not in a crash loop.

        Without the pruning, restart history would accumulate forever and any
        long-lived device would eventually be declared crash-looping.
        """
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        stats = _RestartBookkeeping()
        stats.restart_timestamps = [clock.monotonic()] * RESTART_BUDGET_MAX_RESTARTS
        supervisor._restart_bookkeeping[DEVICE_ID] = stats  # noqa: SLF001
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        # Move every recorded restart out of the window.
        clock.advance(RESTART_BUDGET_WINDOW_S + 1)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()

        assert (DEVICE_ID, "error", "crash_loop") not in registry.transitions
        assert (DEVICE_ID, "starting", "restarting") in registry.transitions

        handling.cancel()
        await settle()

    @pytest.mark.asyncio
    async def test_the_pair_is_respawned_once_the_backoff_elapses(self) -> None:
        """The point of the whole flow: a crashed dongle comes back by itself."""
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry(runnable=(runnable_device(),))
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        spawns_before = len(spawner.spawns)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()
        clock.advance(BACKOFF_START_S)
        await settle()
        clock.advance(IMMEDIATE_EXIT_PROBE_SECONDS)
        await settle()
        await handling

        assert len(spawner.spawns) > spawns_before, "the pair was never respawned"
        assert DEVICE_ID not in supervisor._pending_restart  # noqa: SLF001

        await cancel_background_tasks(supervisor)

    @pytest.mark.asyncio
    async def test_a_device_unplugged_mid_backoff_settles_to_stopped_not_starting(self) -> None:
        """Previously this branch did not exist: the entry was transitioned to

        `starting` and then abandoned — no pair, no watcher, and `starting`
        being absent from the reconcile-ready states meant not even a replug
        could clear it.
        """
        spawner = FakeProcessSpawner()
        registry = ScriptedDeviceRegistry(runnable=(runnable_device(),), enabled=False)
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, registry=registry, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)
        spawns_before = len(spawner.spawns)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()
        registry.runnable = ()  # unplugged while the backoff slept
        clock.advance(BACKOFF_START_S)
        await settle()
        await handling

        assert len(spawner.spawns) == spawns_before, "a departed device must not be respawned"
        assert (DEVICE_ID, "stopped", "disabled") in registry.transitions
        assert DEVICE_ID not in supervisor._pending_restart  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_cancelling_the_backoff_clears_the_pending_restart_marker(self) -> None:
        """`stop_all()` cancels this task mid-sleep.

        A marker left behind would make `reconcile()` believe a restart is
        still pending and refuse to spawn for this device ever again.
        """
        spawner = FakeProcessSpawner()
        clock = FakeClock()
        supervisor = build_supervisor(spawner=spawner, clock=clock)
        await spawn_running_pair(supervisor, spawner)
        await cancel_background_tasks(supervisor)

        handling = asyncio.create_task(supervisor._handle_pair_exit(DEVICE_ID, 1))  # noqa: SLF001
        await settle()
        assert DEVICE_ID in supervisor._pending_restart  # noqa: SLF001

        handling.cancel()
        await settle()

        assert DEVICE_ID not in supervisor._pending_restart  # noqa: SLF001
