"""Tests for spawn-index resolution and the spawn-failure backoff (architecture §5.3).

These cover the two pieces of the supervisor that the hardware incident actually
exercised, and that a passing container would never reveal:

* **Index resolution** must fail loudly with the *right* reason rather than
  guessing an index. The five failure modes point an operator at five different
  remedies — "librtlsdr is not installed" and "librtlsdr sees no dongle" are not
  the same problem, and a dongle that enumerates but will not answer USB control
  transfers is a third thing again. Returning a best-guess index here is how a
  supervisor ends up streaming from the wrong radio.

* **Spawn-failure backoff** must turn a hot retry loop into settle-and-backoff.
  During the incident, routine `reconcile()` churn republished the same
  `index_unresolved` notice three times in seconds, interleaved with unrelated
  wedge notices, burying the one actionable signal.

Both are asserted against a controllable clock, so the backoff schedule is
checked exactly rather than slept through.

Run with:  uv run pytest tests/services/test_supervisor.py
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import cast

import pytest

from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.interfaces.types import RtlSdrUsbStrings
from app.backend.schemas.device import DeviceState, ProcessInfo
from app.backend.services.control_follower import ControlFollowerService
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.event_bus import EventBus, SseMessage
from app.backend.services.supervisor import (
    BACKOFF_MAX_S,
    BACKOFF_START_S,
    IndexResolutionError,
    SupervisorService,
)

from ..fakes.clock import FakeClock

INTERNAL_PORT_BASE = 5000
MAX_DEVICES = 4


class FakeRtlSdrLibrary:
    """An `RtlSdrLibrary` whose enumeration is scripted per index."""

    def __init__(
        self,
        *,
        available: bool = True,
        usb_strings_by_index: dict[int, RtlSdrUsbStrings] | None = None,
        unreadable_indices: frozenset[int] = frozenset(),
        device_count: int | None = None,
    ) -> None:
        self._available = available
        self._usb_strings_by_index = usb_strings_by_index or {}
        self._unreadable_indices = unreadable_indices
        self._device_count = (
            device_count
            if device_count is not None
            else len(self._usb_strings_by_index) + len(unreadable_indices)
        )

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return self._device_count

    def usb_strings(self, index: int) -> RtlSdrUsbStrings:
        if index in self._unreadable_indices:
            # What librtlsdr does when it cannot open an enumerated device.
            raise IndexError(index)
        return self._usb_strings_by_index[index]


class RecordingDeviceRegistry:
    """Records the state transitions the supervisor asks for."""

    def __init__(self) -> None:
        self.transitions: list[tuple[str, DeviceState, str | None]] = []

    def list_runnable_devices(self) -> tuple[object, ...]:
        return ()

    def update_process_info(self, device_id: str, processes: ProcessInfo | None) -> None:
        return None

    async def transition(self, device_id: str, new_state: DeviceState, reason: str | None) -> None:
        self.transitions.append((device_id, new_state, reason))


def usb_strings(
    serial: str, *, manufacturer: str = "Realtek", product: str = "RTL2838"
) -> RtlSdrUsbStrings:
    return RtlSdrUsbStrings(manufacturer=manufacturer, product=product, serial=serial)


def build_supervisor(
    *,
    rtlsdr_library: FakeRtlSdrLibrary | None = None,
    registry: RecordingDeviceRegistry | None = None,
    clock: FakeClock | None = None,
    event_bus: EventBus | None = None,
) -> SupervisorService:
    """A supervisor wired to real collaborators where they are cheap, fakes where not.

    `process_spawner` and `control_follower` are cast placeholders: nothing under
    test here spawns a process, and a stub that is never called is more honest
    than a mock that pretends to be one. Any test that reached them would fail
    loudly on the `None`, which is the intent.
    """
    the_clock = clock or FakeClock()
    return SupervisorService(
        process_spawner=cast(ProcessSpawner, None),
        rtlsdr_library=cast(RtlSdrLibrary, rtlsdr_library or FakeRtlSdrLibrary()),
        device_registry=cast(DeviceRegistry, registry or RecordingDeviceRegistry()),
        clock=the_clock,
        event_bus=event_bus or EventBus(clock=the_clock),
        rtl_tcp_path="/usr/bin/rtl_tcp",
        relay_path="/app/app/backend/relay/rtl_tcp_relay.py",
        internal_port_base=INTERNAL_PORT_BASE,
        max_devices=MAX_DEVICES,
        control_follower=cast(ControlFollowerService, None),
    )


class NoticeCollector:
    """A real `EventBus` subscriber, so dedup is asserted through the actual channel.

    `subscribe()` is an async generator that registers on its first `__anext__`,
    so the collector must be started and given a turn of the loop before anything
    is published — a subscription created but never iterated receives nothing,
    and a test built on one would pass no matter what the supervisor did.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._task: asyncio.Task[None] | None = None
        self.messages: list[SseMessage] = []

    async def __aenter__(self) -> NoticeCollector:
        subscription = self._event_bus.subscribe()

        async def consume() -> None:
            async for message in subscription:
                self.messages.append(message)

        self._task = asyncio.create_task(consume())
        await _settle()
        assert self._event_bus.subscriber_count() == 1, "collector failed to subscribe"
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._task is not None
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def notice_count(self) -> int:
        await _settle()
        return sum(1 for message in self.messages if message.event == "notice")


async def _settle() -> None:
    """Give the bus's queues a few turns to hand messages to the collector."""
    for _ in range(5):
        await asyncio.sleep(0)


class TestResolveSpawnIndex:
    @pytest.mark.asyncio
    async def test_resolves_the_index_reporting_the_requested_serial(self) -> None:
        library = FakeRtlSdrLibrary(
            usb_strings_by_index={0: usb_strings("ADSB-01"), 1: usb_strings("AIS-01")}
        )

        assert await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01") == 1

    @pytest.mark.asyncio
    async def test_reports_librtlsdr_unavailable_when_the_library_never_loaded(self) -> None:
        """Distinct from enumerating zero devices: the remedy is `apt install librtlsdr0`."""
        library = FakeRtlSdrLibrary(available=False)

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01")

        assert raised.value.reason == "librtlsdr_unavailable"

    @pytest.mark.asyncio
    async def test_reports_driver_conflict_when_a_loaded_library_sees_nothing(self) -> None:
        """The DVB kernel driver holding the dongle looks exactly like this."""
        library = FakeRtlSdrLibrary(device_count=0)

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01")

        assert raised.value.reason == "driver_conflict"

    @pytest.mark.asyncio
    async def test_reports_index_unresolved_when_another_serial_answers(self) -> None:
        library = FakeRtlSdrLibrary(usb_strings_by_index={0: usb_strings("ADSB-01")})

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01")

        assert raised.value.reason == "index_unresolved"

    @pytest.mark.asyncio
    async def test_reports_ambiguous_index_when_two_dongles_share_a_serial(self) -> None:
        """Untagged dongles ship with the same serial; guessing one would be a coin toss."""
        library = FakeRtlSdrLibrary(
            usb_strings_by_index={0: usb_strings("00000001"), 1: usb_strings("00000001")}
        )

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("00000001")

        assert raised.value.reason == "ambiguous_index"
        assert "flash a unique serial" in str(raised.value)

    @pytest.mark.asyncio
    async def test_reports_unresponsive_device_for_wholly_empty_usb_strings(self) -> None:
        """On the bus, not talking — the shape the hardware incident actually took."""
        library = FakeRtlSdrLibrary(
            usb_strings_by_index={0: RtlSdrUsbStrings(manufacturer="", product="", serial="")}
        )

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01")

        assert raised.value.reason == "unresponsive_device"

    @pytest.mark.asyncio
    async def test_treats_an_unreadable_index_as_unresponsive_too(self) -> None:
        """librtlsdr raising is no different from it returning empty strings."""
        library = FakeRtlSdrLibrary(unreadable_indices=frozenset({0}))

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01")

        assert raised.value.reason == "unresponsive_device"

    @pytest.mark.asyncio
    async def test_correlates_the_sysfs_serial_into_the_unresponsive_message(self) -> None:
        """The strongest signal available: sysfs saw a serial, librtlsdr cannot read one."""
        library = FakeRtlSdrLibrary(unreadable_indices=frozenset({0}))

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01")

        assert "'AIS-01'" in str(raised.value)

    @pytest.mark.asyncio
    async def test_omits_the_correlation_when_sysfs_reported_no_serial(self) -> None:
        """No serial to correlate; the sentence would read as an empty accusation."""
        library = FakeRtlSdrLibrary(unreadable_indices=frozenset({0}))

        with pytest.raises(IndexResolutionError) as raised:
            await build_supervisor(rtlsdr_library=library).resolve_spawn_index("")

        assert "sysfs previously reported" not in str(raised.value)

    @pytest.mark.asyncio
    async def test_a_readable_match_wins_over_an_unresponsive_sibling(self) -> None:
        """One dead dongle must not stop a healthy one from starting."""
        library = FakeRtlSdrLibrary(
            usb_strings_by_index={1: usb_strings("AIS-01")},
            unreadable_indices=frozenset({0}),
        )

        assert await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01") == 1

    @pytest.mark.asyncio
    async def test_partial_usb_strings_still_count_as_responsive(self) -> None:
        """Many dongles report no manufacturer; only *wholly* empty means unresponsive."""
        library = FakeRtlSdrLibrary(
            usb_strings_by_index={0: RtlSdrUsbStrings(manufacturer="", product="", serial="AIS-01")}
        )

        assert await build_supervisor(rtlsdr_library=library).resolve_spawn_index("AIS-01") == 0


class TestSpawnFailureBackoff:
    @pytest.mark.asyncio
    async def test_a_device_with_no_recorded_failure_may_retry_immediately(self) -> None:
        supervisor = build_supervisor()

        assert supervisor._spawn_retry_ready("serial:AIS-01") is True

    @pytest.mark.asyncio
    async def test_a_fresh_failure_blocks_the_next_retry(self) -> None:
        supervisor = build_supervisor()

        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")

        assert supervisor._spawn_retry_ready("serial:AIS-01") is False

    @pytest.mark.asyncio
    async def test_the_retry_opens_once_the_backoff_has_elapsed(self) -> None:
        clock = FakeClock()
        supervisor = build_supervisor(clock=clock)

        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")
        clock.advance(BACKOFF_START_S)

        assert supervisor._spawn_retry_ready("serial:AIS-01") is True

    @pytest.mark.asyncio
    async def test_the_backoff_doubles_with_each_failure(self) -> None:
        clock = FakeClock()
        supervisor = build_supervisor(clock=clock)

        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "first")
        clock.advance(BACKOFF_START_S)
        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "second")

        # Still closed after one interval, because the wait is now two.
        clock.advance(BACKOFF_START_S)
        assert supervisor._spawn_retry_ready("serial:AIS-01") is False
        clock.advance(BACKOFF_START_S)
        assert supervisor._spawn_retry_ready("serial:AIS-01") is True

    @pytest.mark.asyncio
    async def test_the_backoff_stops_doubling_at_the_ceiling(self) -> None:
        """Unbounded doubling would eventually park a recoverable device for hours."""
        clock = FakeClock()
        supervisor = build_supervisor(clock=clock)

        for attempt in range(20):
            await supervisor._record_spawn_failure(
                "serial:AIS-01", "index_unresolved", f"attempt {attempt}"
            )
            clock.advance(BACKOFF_MAX_S * 2)

        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "last")
        clock.advance(BACKOFF_MAX_S)

        assert supervisor._spawn_retry_ready("serial:AIS-01") is True

    @pytest.mark.asyncio
    async def test_each_device_backs_off_independently(self) -> None:
        """One dead dongle must not delay a second one's first attempt."""
        supervisor = build_supervisor()

        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")

        assert supervisor._spawn_retry_ready("serial:ADSB-01") is True

    @pytest.mark.asyncio
    async def test_every_failure_updates_the_registry_even_when_deduped(self) -> None:
        """`GET /api/status` must stay accurate on attempts that publish nothing."""
        registry = RecordingDeviceRegistry()
        supervisor = build_supervisor(registry=registry)

        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")
        await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")

        assert registry.transitions == [
            ("serial:AIS-01", "error", "index_unresolved"),
            ("serial:AIS-01", "error", "index_unresolved"),
        ]

    @pytest.mark.asyncio
    async def test_an_identical_repeat_failure_is_not_republished(self) -> None:
        """The incident's noise: the same notice three times in seconds, burying the signal."""
        clock = FakeClock()
        event_bus = EventBus(clock=clock)
        supervisor = build_supervisor(clock=clock, event_bus=event_bus)

        async with NoticeCollector(event_bus) as collector:
            await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")
            await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")

            assert await collector.notice_count() == 1

    @pytest.mark.asyncio
    async def test_a_different_failure_is_published(self) -> None:
        """Dedup is per exact failure — a device that changes symptom is news."""
        clock = FakeClock()
        event_bus = EventBus(clock=clock)
        supervisor = build_supervisor(clock=clock, event_bus=event_bus)

        async with NoticeCollector(event_bus) as collector:
            await supervisor._record_spawn_failure("serial:AIS-01", "index_unresolved", "no index")
            await supervisor._record_spawn_failure(
                "serial:AIS-01", "unresponsive_device", "no answer"
            )

            assert await collector.notice_count() == 2


class TestInternalPortAllocation:
    def test_assigns_the_lowest_free_loopback_port(self) -> None:
        supervisor = build_supervisor()

        assert supervisor._allocate_internal_port("serial:AIS-01") == INTERNAL_PORT_BASE

    def test_gives_each_device_a_distinct_port(self) -> None:
        supervisor = build_supervisor()

        first = supervisor._allocate_internal_port("serial:AIS-01")
        second = supervisor._allocate_internal_port("serial:ADSB-01")

        assert (first, second) == (INTERNAL_PORT_BASE, INTERNAL_PORT_BASE + 1)

    def test_returns_none_once_the_range_is_exhausted(self) -> None:
        """`max_devices` is the real ceiling; silently reusing a port would cross two streams."""
        supervisor = build_supervisor()
        for index in range(MAX_DEVICES):
            supervisor._allocate_internal_port(f"serial:D{index}")

        assert supervisor._allocate_internal_port("serial:one-too-many") is None

    def test_a_released_port_is_reused(self) -> None:
        """Otherwise a replugged dongle would exhaust the range over a long uptime."""
        supervisor = build_supervisor()
        for index in range(MAX_DEVICES):
            supervisor._allocate_internal_port(f"serial:D{index}")

        supervisor._release_internal_port("serial:D1")

        assert supervisor._allocate_internal_port("serial:new") == INTERNAL_PORT_BASE + 1

    def test_releasing_an_unknown_device_is_harmless(self) -> None:
        """Called on paths where the device may never have been allocated one."""
        supervisor = build_supervisor()

        supervisor._release_internal_port("serial:never-allocated")

        assert supervisor._allocate_internal_port("serial:AIS-01") == INTERNAL_PORT_BASE
