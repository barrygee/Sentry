"""Acquiring, renewing and releasing claims on dongles (`device_reservations`).

Every question here reduces to one: **is there a live lease, and is the caller
the one holding it?** A lease is live while `expires_at` is in the future, which
is checked against the clock on every read rather than swept on a timer — a
sweep that stopped running would silently start reporting stale locks as live,
which is the exact failure the expiry exists to prevent.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backend.interfaces.clock import Clock
from app.backend.models import DeviceReservationModel
from app.backend.schemas.reservation import DeviceReservation


class ReservationHeldError(Exception):
    """Raised when another consumer holds a live lease on the device.

    Carries the current holder so the caller can say *who* has it. A bare
    "device busy" would leave an operator with nothing to act on — the useful
    part of the refusal is the name.
    """

    def __init__(self, reservation: DeviceReservation) -> None:
        super().__init__(f"Device is reserved by {reservation.holder}.")
        self.reservation = reservation


def _device_id_of(model: DeviceReservationModel) -> str:
    return f"{model.identity_kind}:{model.identity_key}"


def _to_schema(model: DeviceReservationModel) -> DeviceReservation:
    return DeviceReservation(
        device_id=_device_id_of(model),
        holder=model.holder,
        label=model.label,
        reserved_at=model.reserved_at,
        expires_at=model.expires_at,
    )


class DeviceReservationService:
    """Reads and writes claims on dongles, keyed by device identity."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def get_reservation(
        self, identity_kind: str, identity_key: str
    ) -> DeviceReservation | None:
        """Return the live claim on this device, or `None` when it is free.

        A lapsed row reads as free and is deleted on sight. Leaving it would
        mean every later read re-deciding the same expiry, and would show a
        stale holder in any query that forgot to.
        """
        async with self._session_factory() as session:
            model = await self._live_row(session, identity_kind, identity_key)
            return _to_schema(model) if model is not None else None

    async def acquire(
        self,
        identity_kind: str,
        identity_key: str,
        *,
        holder: str,
        label: str,
        ttl_seconds: int,
        force: bool = False,
    ) -> DeviceReservation:
        """Take or renew a lease, returning it.

        Renewing is the same call as acquiring, deliberately: a holder should not
        have to know whether its previous lease has lapsed while it was away, and
        making renewal a separate endpoint would mean handling the case where it
        expired a moment before the renewal landed.

        `force` takes the device from a live holder — the operator's override.
        Without it a claim on a device someone else holds raises
        `ReservationHeldError` rather than silently winning.
        """
        now = self._clock.now_ms()
        expires_at = now + ttl_seconds * 1000

        async with self._session_factory() as session:
            existing = await self._live_row(session, identity_kind, identity_key)

            if existing is not None and existing.holder != holder and not force:
                raise ReservationHeldError(_to_schema(existing))

            if existing is not None:
                # A renewal keeps `reserved_at`, so the console can say how long
                # a consumer has held the device rather than how recently it
                # checked in. A takeover resets it: it is a new claim by someone
                # else, and inheriting the old start time would misreport it.
                if existing.holder != holder:
                    existing.holder = holder
                    existing.reserved_at = now
                existing.label = label
                existing.expires_at = expires_at
                await session.commit()
                return _to_schema(existing)

            model = DeviceReservationModel(
                identity_kind=identity_kind,
                identity_key=identity_key,
                holder=holder,
                label=label,
                reserved_at=now,
                expires_at=expires_at,
            )
            session.add(model)
            await session.commit()
            return _to_schema(model)

    async def release(
        self,
        identity_kind: str,
        identity_key: str,
        *,
        holder: str,
        force: bool = False,
    ) -> bool:
        """Release this device's claim. True when something was released.

        Only the holder may release, unless `force`. Otherwise a consumer could
        drop somebody else's lease — the same harm as taking it, arrived at from
        the other direction, and without even meaning to claim the device.

        Idempotent: releasing a device that is already free is a success, not an
        error. A holder shutting down should not have to care whether its lease
        happened to lapse a moment earlier.
        """
        async with self._session_factory() as session:
            existing = await self._live_row(session, identity_kind, identity_key)
            if existing is None:
                return False
            if existing.holder != holder and not force:
                raise ReservationHeldError(_to_schema(existing))
            await session.delete(existing)
            await session.commit()
            return True

    async def list_reservations(self) -> dict[str, DeviceReservation]:
        """Every live claim, keyed by `device_id`.

        One query for the whole set, because the callers that need this — the
        device list, the Sentinel export — would otherwise issue a lookup per
        device on a path that already runs per poll.
        """
        now = self._clock.now_ms()
        async with self._session_factory() as session:
            await self._purge_expired(session, now)
            result = await session.execute(
                select(DeviceReservationModel).where(DeviceReservationModel.expires_at > now)
            )
            return {_device_id_of(model): _to_schema(model) for model in result.scalars().all()}

    async def _live_row(
        self, session: AsyncSession, identity_kind: str, identity_key: str
    ) -> DeviceReservationModel | None:
        """The unexpired row for this device, deleting it if it has lapsed."""
        result = await session.execute(
            select(DeviceReservationModel).where(
                DeviceReservationModel.identity_kind == identity_kind,
                DeviceReservationModel.identity_key == identity_key,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        if model.expires_at <= self._clock.now_ms():
            await session.delete(model)
            await session.commit()
            return None
        return model

    async def _purge_expired(self, session: AsyncSession, now: int) -> None:
        """Drop lapsed rows. Housekeeping, not correctness — reads already ignore them."""
        await session.execute(
            delete(DeviceReservationModel).where(DeviceReservationModel.expires_at <= now)
        )
        await session.commit()
