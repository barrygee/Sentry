"""Tests for the `PATCH /api/devices/{id}` tuning re-assert.

The bug this guards: tuning only reaches the dongle as `rtl_tcp` startup
arguments, and the supervisor restarts a pair only when a stored value changes.
A raw rtl_tcp client could retune the dongle through the relay without Sentry
knowing, and a holder re-sending the *same* values on every lease renewal then
changed nothing — the ADS-B dongle sat on 124.375 MHz while the record said
1090 MHz. So a patch that mentions live tuning must push the stored tuning onto
the running dongle even when nothing in the record moved.

The route handler is called directly rather than over HTTP: this host has no
dongle, so a real PATCH fails `unknown_device` before reaching the code under
test (see `TestThePatchGate` in `test_reservation_routes.py`).

Run with:  uv run pytest tests/reservations/test_tuning_reassert.py
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.backend.routers import devices
from app.backend.schemas.device import DevicePatch, DeviceRecord
from app.backend.services.control_follower import (
    ControlFollowerService,
    TuneOutcome,
    TuneRequest,
)
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.device_reservations import DeviceReservationService
from app.backend.services.port_allocator import PortAllocatorService

DEVICE_ID = "serial:97710286"


class RecordingFollower:
    """Stands in for `ControlFollowerService`, recording every `apply_tune` call."""

    def __init__(self, outcome: TuneOutcome | None = None, error: OSError | None = None) -> None:
        self.calls: list[tuple[str, TuneRequest]] = []
        self._outcome = outcome or TuneOutcome(applied=True, tuning_deferred=False)
        self._error = error

    async def apply_tune(self, device_id: str, request: TuneRequest) -> TuneOutcome:
        self.calls.append((device_id, request))
        if self._error is not None:
            raise self._error
        return self._outcome


def stored_record(**tuning: Any) -> DeviceRecord:
    """The record `apply_device_configuration` returns: only its tuning is read."""
    fields = {
        "center_hz": 1_090_000_000,
        "sample_rate": 2_400_000,
        "gain_db": 49.6,
        "gain_auto": False,
        **tuning,
    }
    return cast(DeviceRecord, SimpleNamespace(**fields))


@pytest.fixture
def stub_configuration(monkeypatch: pytest.MonkeyPatch) -> dict[str, DeviceRecord]:
    """Bypass the reservation gate and the registry; return a settable stored record."""
    stored = {"record": stored_record()}

    async def allow_tuning(*_arguments: object) -> None:
        return None

    async def apply_configuration(*_arguments: object) -> DeviceRecord:
        return stored["record"]

    monkeypatch.setattr(devices, "_require_tuning_allowed", allow_tuning)
    monkeypatch.setattr(devices, "apply_device_configuration", apply_configuration)
    return stored


async def patch_with(follower: RecordingFollower, **fields: Any) -> DeviceRecord:
    return await devices.patch_device(
        patch=DevicePatch(**fields),
        device_id=DEVICE_ID,
        device_registry=cast(DeviceRegistry, None),
        port_allocator=cast(PortAllocatorService, None),
        reservations=cast(DeviceReservationService, None),
        control_follower=cast(ControlFollowerService, follower),
        holder="sentinel:aaa",
    )


class TestWhenTheRelayIsTold:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fields",
        [
            pytest.param({"center_hz": 1_090_000_000}, id="centre-frequency"),
            pytest.param({"sample_rate": 2_400_000}, id="sample-rate"),
            pytest.param({"gain_db": 49.6}, id="gain"),
            pytest.param({"gain_auto": False}, id="gain-mode"),
        ],
    )
    async def test_any_live_tuning_field_pushes_the_stored_tuning(
        self, stub_configuration: dict[str, DeviceRecord], fields: dict[str, Any]
    ) -> None:
        follower = RecordingFollower()

        await patch_with(follower, **fields)

        assert follower.calls == [
            (
                DEVICE_ID,
                TuneRequest(
                    center_hz=1_090_000_000, sample_rate=2_400_000, gain_db=49.6, gain_auto=False
                ),
            )
        ]

    @pytest.mark.asyncio
    async def test_an_unchanged_renewal_still_pushes(
        self, stub_configuration: dict[str, DeviceRecord]
    ) -> None:
        # The whole point: Sentinel renews with exactly the stored values, and
        # that must still reach a dongle somebody else moved.
        follower = RecordingFollower()

        await patch_with(
            follower, center_hz=1_090_000_000, sample_rate=2_400_000, gain_auto=False, gain_db=49.6
        )
        await patch_with(
            follower, center_hz=1_090_000_000, sample_rate=2_400_000, gain_auto=False, gain_db=49.6
        )

        assert len(follower.calls) == 2

    @pytest.mark.asyncio
    async def test_the_stored_tuning_is_sent_not_the_patch(
        self, stub_configuration: dict[str, DeviceRecord]
    ) -> None:
        # A partial patch is merged into the record; the dongle gets the whole
        # stored tuning, so a drifted sample rate is fixed by a frequency patch.
        stub_configuration["record"] = stored_record(center_hz=137_100_000)
        follower = RecordingFollower()

        await patch_with(follower, center_hz=137_100_000)

        assert follower.calls[0][1].sample_rate == 2_400_000
        assert follower.calls[0][1].center_hz == 137_100_000

    @pytest.mark.asyncio
    async def test_agc_sends_no_gain(self, stub_configuration: dict[str, DeviceRecord]) -> None:
        # rtl_tcp ignores a manual gain under AGC; sending the stale stored one
        # would make the relay switch AGC off again.
        stub_configuration["record"] = stored_record(gain_auto=True, gain_db=30.0)
        follower = RecordingFollower()

        await patch_with(follower, gain_auto=True)

        request = follower.calls[0][1]
        assert request.gain_auto is True
        assert request.gain_db is None


class TestWhenTheRelayIsLeftAlone:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fields",
        [
            pytest.param({"notes": "a note"}, id="metadata"),
            pytest.param({"antenna": "Discone"}, id="antenna"),
            pytest.param({"ppm_correction": 5}, id="restart-only-tuning"),
            pytest.param({"enabled": True}, id="enabled"),
        ],
    )
    async def test_patches_without_live_tuning_do_not_touch_the_dongle(
        self, stub_configuration: dict[str, DeviceRecord], fields: dict[str, Any]
    ) -> None:
        follower = RecordingFollower()

        await patch_with(follower, **fields)

        assert follower.calls == []


class TestBestEffort:
    @pytest.mark.asyncio
    async def test_returns_the_record(self, stub_configuration: dict[str, DeviceRecord]) -> None:
        record = await patch_with(RecordingFollower(), center_hz=1_090_000_000)

        assert record is stub_configuration["record"]

    @pytest.mark.asyncio
    async def test_a_deferred_push_still_succeeds_and_says_why(
        self, stub_configuration: dict[str, DeviceRecord], caplog: pytest.LogCaptureFixture
    ) -> None:
        # A stopped pair or a held token: nothing to fight, so the PATCH stands.
        follower = RecordingFollower(outcome=TuneOutcome(applied=False, tuning_deferred=True))

        with caplog.at_level(logging.INFO, logger=devices.__name__):
            record = await patch_with(follower, center_hz=1_090_000_000)

        assert record is stub_configuration["record"]
        assert any("deferred" in message for message in caplog.messages)

    @pytest.mark.asyncio
    async def test_an_applied_push_logs_nothing(
        self, stub_configuration: dict[str, DeviceRecord], caplog: pytest.LogCaptureFixture
    ) -> None:
        # Every 30 s lease renewal lands here; a healthy one must stay quiet.
        with caplog.at_level(logging.INFO, logger=devices.__name__):
            await patch_with(RecordingFollower(), center_hz=1_090_000_000)

        assert caplog.messages == []

    @pytest.mark.asyncio
    async def test_a_dead_control_connection_does_not_fail_the_patch(
        self, stub_configuration: dict[str, DeviceRecord], caplog: pytest.LogCaptureFixture
    ) -> None:
        follower = RecordingFollower(error=ConnectionResetError("relay went away"))

        with caplog.at_level(logging.WARNING, logger=devices.__name__):
            record = await patch_with(follower, center_hz=1_090_000_000)

        assert record is stub_configuration["record"]
        assert any("relay went away" in message for message in caplog.messages)
