"""`/api/devices/{id}/reservation` — claiming a dongle so nothing else retunes it.

A dongle can serve exactly one tuned purpose at a time. That is physics, not a
rule invented here; what this adds is making it *visible and enforced*, so two
consumers wanting the same device get an answer instead of quietly fighting over
its centre frequency.

**Every reservation is a lease.** The holder states how long it wants the device
for and renews while it is still using it. Nothing is held for ever because
nothing can be: a browser tab closes, a container is killed, a network drops,
and none of those run a release. An expiring lease is the only release path that
works when the holder is no longer there to ask.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MINIMUM_TTL_SECONDS = 5
MAXIMUM_TTL_SECONDS = 3600
DEFAULT_TTL_SECONDS = 120
"""Two minutes: long enough to ride out a lost renewal or two, short enough that
a dongle whose holder has vanished is usable again within a coffee's reach."""


class ReservationRequest(BaseModel):
    """`POST /api/devices/{id}/reservation` body — acquire or renew a lease."""

    model_config = ConfigDict(extra="forbid")

    holder: str = Field(
        min_length=1,
        max_length=128,
        description="Opaque consumer id, e.g. sentinel:<instance-uuid>",
    )
    """Opaque to Sentry on purpose.

    Sentry arbitrates between consumers without needing to know what they are,
    and a closed vocabulary here would need extending every time something new
    wanted a dongle. It must be *stable* for the holder, though — it is the only
    thing that distinguishes "renewing my own lease" from "stealing someone
    else's", so a value regenerated per request would lock a consumer out of the
    device it is holding.
    """

    label: str = Field(
        default="",
        max_length=120,
        description='Operator-facing, e.g. "Sentinel — AIR (ADS-B)"',
    )
    """What the console shows. Without it the UI could only display the opaque
    `holder` at an operator and hope they recognised it."""

    ttl_seconds: int = Field(
        default=DEFAULT_TTL_SECONDS,
        ge=MINIMUM_TTL_SECONDS,
        le=MAXIMUM_TTL_SECONDS,
        description="How long the lease lasts unless renewed",
    )
    """Bounded at both ends. Too short and a consumer spends its life renewing;
    too long and a crashed holder keeps a dongle for hours, which is the failure
    the lease exists to prevent."""

    force: bool = Field(
        default=False,
        description="Take the device from its current holder. For the operator, never a machine",
    )
    """The override an operator standing at the machine needs.

    It is their hardware, and a lock they cannot break is a lock that will one
    day strand them. It is a deliberate act rather than the default because the
    holder finds out only by failing its next renewal — which is recoverable,
    but should not happen by accident.
    """


class DeviceReservation(BaseModel):
    """A claim, as reported by the API.

    Carries no `is_live` of its own: liveness is a question about *now*, and a
    model cannot answer it without a clock. Giving it one would let a
    deserialised object insist a long-lapsed lease is still good. The service
    decides, against the same clock the rest of Sentry uses.
    """

    model_config = ConfigDict(frozen=True)

    device_id: str
    holder: str
    label: str = ""
    reserved_at: int = Field(description="Unix ms the claim was first taken")
    expires_at: int = Field(description="Unix ms it lapses unless renewed")


class ReservationState(BaseModel):
    """`GET`-shaped view of a device's claim: present, or explicitly absent.

    A wrapper rather than a bare `DeviceReservation | None` so the response has
    somewhere to say *why* there is no reservation — expired reads differently
    from never claimed, and an operator watching a device change hands benefits
    from the difference.
    """

    model_config = ConfigDict(frozen=True)

    reserved: bool
    reservation: DeviceReservation | None = None
