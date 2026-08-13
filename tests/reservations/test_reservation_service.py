"""Tests for the lease semantics behind `device_reservations`.

The lease's *expiry* is the property worth defending hardest. Every explicit
release path fails in the real world — a tab closes, a container is killed, a
network partitions — and without expiry each of those leaves a dongle locked
until somebody edits the database. The tests here drive a `FakeClock` forward
rather than sleeping, so "a lapsed lease reads as free" is asserted exactly.

The second property is holder identity: renewing your own lease and taking
somebody else's are the same request shape, and only the holder distinguishes
them. Confusing the two would either lock a consumer out of a device it holds
or let anything walk off with a device in use.

Run with:  uv run pytest tests/reservations
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.backend.models import Base
from app.backend.services.device_reservations import (
    DeviceReservationService,
    ReservationHeldError,
)

from ..fakes.clock import FakeClock

KIND = "serial"
KEY = "ADSB-01"
HOLDER = "sentinel:aaa"
OTHER_HOLDER = "sentinel:bbb"


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reservations.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start_ms=1_700_000_000_000)


@pytest.fixture
def service(
    session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> DeviceReservationService:
    return DeviceReservationService(session_factory, clock)


class TestClaimingAFreeDevice:
    @pytest.mark.asyncio
    async def test_an_unclaimed_device_reads_as_free(
        self, service: DeviceReservationService
    ) -> None:
        assert await service.get_reservation(KIND, KEY) is None

    @pytest.mark.asyncio
    async def test_acquiring_records_the_holder_and_label(
        self, service: DeviceReservationService
    ) -> None:
        reservation = await service.acquire(
            KIND, KEY, holder=HOLDER, label="Sentinel — AIR", ttl_seconds=120
        )

        assert reservation.holder == HOLDER
        assert reservation.label == "Sentinel — AIR"
        assert reservation.device_id == f"{KIND}:{KEY}"

    @pytest.mark.asyncio
    async def test_the_lease_expires_ttl_seconds_after_it_is_taken(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        reservation = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert reservation.expires_at == clock.now_ms() + 120_000

    @pytest.mark.asyncio
    async def test_a_claim_is_readable_afterwards(self, service: DeviceReservationService) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        stored = await service.get_reservation(KIND, KEY)

        assert stored is not None
        assert stored.holder == HOLDER

    @pytest.mark.asyncio
    async def test_claims_on_different_devices_are_independent(
        self, service: DeviceReservationService
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert await service.get_reservation(KIND, "OTHER-DONGLE") is None


class TestTheLeaseExpiring:
    """The safety property: nothing is held for ever, because nothing can be."""

    @pytest.mark.asyncio
    async def test_a_lapsed_lease_reads_as_free(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        clock.advance(121)

        assert await service.get_reservation(KIND, KEY) is None

    @pytest.mark.asyncio
    async def test_a_lease_is_still_live_the_moment_before_it_lapses(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        clock.advance(119)

        assert await service.get_reservation(KIND, KEY) is not None

    @pytest.mark.asyncio
    async def test_a_lapsed_device_can_be_claimed_by_somebody_else(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        # The recovery path after a holder vanishes without releasing.
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        clock.advance(121)

        taken = await service.acquire(KIND, KEY, holder=OTHER_HOLDER, label="", ttl_seconds=120)

        assert taken.holder == OTHER_HOLDER

    @pytest.mark.asyncio
    async def test_renewing_keeps_a_lease_alive_indefinitely(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        for _ in range(10):
            clock.advance(30)
            await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert await service.get_reservation(KIND, KEY) is not None


class TestRenewingAndTakingOver:
    @pytest.mark.asyncio
    async def test_renewing_extends_the_expiry(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        first = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        clock.advance(60)

        renewed = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert renewed.expires_at > first.expires_at

    @pytest.mark.asyncio
    async def test_renewing_keeps_the_original_start_time(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        # So the console can say how long a consumer has held the device, rather
        # than how recently it checked in.
        first = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        clock.advance(60)

        renewed = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert renewed.reserved_at == first.reserved_at

    @pytest.mark.asyncio
    async def test_renewing_does_not_create_a_second_row(
        self, service: DeviceReservationService
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert len(await service.list_reservations()) == 1

    @pytest.mark.asyncio
    async def test_another_holder_is_refused(self, service: DeviceReservationService) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="Sentinel — AIR", ttl_seconds=120)

        with pytest.raises(ReservationHeldError) as raised:
            await service.acquire(KIND, KEY, holder=OTHER_HOLDER, label="", ttl_seconds=120)

        # The refusal names who has it — "device busy" alone leaves the caller
        # with nothing to decide from.
        assert raised.value.reservation.holder == HOLDER
        assert raised.value.reservation.label == "Sentinel — AIR"

    @pytest.mark.asyncio
    async def test_a_refused_claim_leaves_the_existing_lease_untouched(
        self, service: DeviceReservationService
    ) -> None:
        original = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        with pytest.raises(ReservationHeldError):
            await service.acquire(KIND, KEY, holder=OTHER_HOLDER, label="", ttl_seconds=999)

        current = await service.get_reservation(KIND, KEY)
        assert current is not None
        assert current.holder == HOLDER
        assert current.expires_at == original.expires_at

    @pytest.mark.asyncio
    async def test_force_takes_the_device(self, service: DeviceReservationService) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        taken = await service.acquire(
            KIND, KEY, holder=OTHER_HOLDER, label="", ttl_seconds=120, force=True
        )

        assert taken.holder == OTHER_HOLDER

    @pytest.mark.asyncio
    async def test_a_takeover_resets_the_start_time(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        # It is a new claim by somebody else; inheriting the old start would
        # report the new holder as having held it since before they had it.
        first = await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        clock.advance(60)

        taken = await service.acquire(
            KIND, KEY, holder=OTHER_HOLDER, label="", ttl_seconds=120, force=True
        )

        assert taken.reserved_at > first.reserved_at


class TestReleasing:
    @pytest.mark.asyncio
    async def test_the_holder_can_release(self, service: DeviceReservationService) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        released = await service.release(KIND, KEY, holder=HOLDER)

        assert released is True
        assert await service.get_reservation(KIND, KEY) is None

    @pytest.mark.asyncio
    async def test_releasing_a_free_device_is_not_an_error(
        self, service: DeviceReservationService
    ) -> None:
        # A holder shutting down should not have to care whether its lease
        # happened to lapse a moment earlier.
        assert await service.release(KIND, KEY, holder=HOLDER) is False

    @pytest.mark.asyncio
    async def test_another_holder_cannot_release(self, service: DeviceReservationService) -> None:
        # Dropping somebody else's lease is the same harm as taking it, reached
        # from the other side.
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        with pytest.raises(ReservationHeldError):
            await service.release(KIND, KEY, holder=OTHER_HOLDER)

        assert await service.get_reservation(KIND, KEY) is not None

    @pytest.mark.asyncio
    async def test_force_releases_somebody_elses_lease(
        self, service: DeviceReservationService
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)

        assert await service.release(KIND, KEY, holder=OTHER_HOLDER, force=True) is True

    @pytest.mark.asyncio
    async def test_a_released_device_can_be_claimed_immediately(
        self, service: DeviceReservationService
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        await service.release(KIND, KEY, holder=HOLDER)

        taken = await service.acquire(KIND, KEY, holder=OTHER_HOLDER, label="", ttl_seconds=120)

        assert taken.holder == OTHER_HOLDER


class TestListingLiveClaims:
    @pytest.mark.asyncio
    async def test_lists_claims_keyed_by_device_id(self, service: DeviceReservationService) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        await service.acquire("usb", "1-1.2", holder=OTHER_HOLDER, label="", ttl_seconds=120)

        listed = await service.list_reservations()

        assert set(listed) == {"serial:ADSB-01", "usb:1-1.2"}

    @pytest.mark.asyncio
    async def test_omits_lapsed_claims(
        self, service: DeviceReservationService, clock: FakeClock
    ) -> None:
        await service.acquire(KIND, KEY, holder=HOLDER, label="", ttl_seconds=120)
        await service.acquire("usb", "1-1.2", holder=OTHER_HOLDER, label="", ttl_seconds=600)

        clock.advance(121)
        listed = await service.list_reservations()

        assert set(listed) == {"usb:1-1.2"}

    @pytest.mark.asyncio
    async def test_is_empty_when_nothing_is_claimed(
        self, service: DeviceReservationService
    ) -> None:
        assert await service.list_reservations() == {}
