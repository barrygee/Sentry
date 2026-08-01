"""Validate and reserve `(P, P+2)` port pairs (architecture §8).

Pure rule evaluation plus one optional bind probe. Never picks a port
unasked — it validates an operator's choice and *suggests* a next free one;
auto-assignment was rejected because the port is part of Sentinel's stored
configuration (architecture §8 intro).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from app.backend.interfaces.netprobe import PortProber
from app.backend.interfaces.repository import DeviceRepository

PortRejectionCode = Literal[
    "port_out_of_range",
    "port_conflict",
    "port_reserved_http",
    "port_reserved_internal",
    "port_reserved_operator",
    "port_in_use",
]

DEFAULT_SUGGESTION_START_PORT = 1234
"""The lowest port `suggest_next()` considers."""

SUGGESTION_PORT_STEP = 4
"""`suggest_next()` steps by 4 (1234, 1238, 1242…) rather than 1: every
candidate reserves a `(P, P+2)` pair, so stepping by the pair's own width
skips over ranges a just-rejected candidate has already implicated, without
skipping any candidate that could still be free after one is taken."""

MAX_SUGGESTION_ATTEMPTS = 2_000
"""Bounds `suggest_next()`'s worst case. Every candidate previously cost two
`list_all()` round-trips plus two *synchronous* socket binds — on a densely
packed allocation that could run up to ~64,000 iterations while blocking the
event loop (and therefore every open SSE stream) on each bind call. Reserved
pairs are now fetched once per `suggest_next()` call (not per candidate) and
each bind probe is offloaded via `asyncio.to_thread`, but the search is still
capped here as a hard ceiling on how long one `GET /api/devices` can take."""


@dataclass(frozen=True, slots=True)
class PortValidationResult:
    """The outcome of validating one proposed `output_port`."""

    is_valid: bool
    rejection_code: PortRejectionCode | None
    conflicts_with: str | None = None
    """The conflicting device's `device_id`, populated only for `port_conflict`."""


class PortAllocatorService:
    """Evaluates the six port-assignment rules (architecture §8) for one proposed port."""

    def __init__(
        self,
        port_prober: PortProber,
        device_repository: DeviceRepository,
        http_port: int,
        internal_port_base: int,
        max_devices: int,
        operator_reserved_ports: frozenset[int],
    ) -> None:
        self._port_prober = port_prober
        self._device_repository = device_repository
        self._http_port = http_port
        self._internal_port_base = internal_port_base
        self._max_devices = max_devices
        self._operator_reserved_ports = operator_reserved_ports

    async def validate(
        self, proposed_port: int, requesting_device_id: str | None
    ) -> PortValidationResult:
        """Validate `proposed_port` (reserving `{proposed_port, proposed_port + 2}`).

        `requesting_device_id` exempts that device's own already-reserved
        pair from the conflict and bind-probe checks, so re-saving a device's
        current port is never rejected as colliding with itself. Rules are
        evaluated in architecture §8 order, returning on the first failure.
        """
        reserved_pairs = await self._reserved_pairs()
        return await self._validate_with_reserved_pairs(
            proposed_port, requesting_device_id, reserved_pairs
        )

    async def _validate_with_reserved_pairs(
        self,
        proposed_port: int,
        requesting_device_id: str | None,
        reserved_pairs: list[tuple[str, int, int]],
    ) -> PortValidationResult:
        """`validate()`'s rule evaluation against an already-fetched `reserved_pairs`.

        Split out so `suggest_next()` can fetch `reserved_pairs` exactly
        once for its whole search rather than once per candidate port (the
        previous cost: two `list_all()` round-trips *per candidate*, up to
        ~64,000 of them on a densely packed allocation).
        """
        control_port = proposed_port + 2

        # Rule 1: range. `P + 2` must not exceed 65535, and `P` itself must
        # leave room for `P + 2` to stay a valid 16-bit port.
        if proposed_port < 1024 or control_port > 65535:
            return PortValidationResult(is_valid=False, rejection_code="port_out_of_range")

        # Rule 2: collision with another device's reserved pair — including
        # disabled and absent devices, whose reservations still block a new
        # assignment. `requesting_device_id` exempts a device re-saving its
        # own current port.
        own_pair: tuple[int, int] | None = None
        for other_device_id, other_port, other_control_port in reserved_pairs:
            if other_device_id == requesting_device_id:
                own_pair = (other_port, other_control_port)
                continue
            other_pair = {other_port, other_control_port}
            if proposed_port in other_pair or control_port in other_pair:
                return PortValidationResult(
                    is_valid=False,
                    rejection_code="port_conflict",
                    conflicts_with=other_device_id,
                )

        # Rule 3: the HTTP/SPA port.
        if proposed_port == self._http_port or control_port == self._http_port:
            return PortValidationResult(is_valid=False, rejection_code="port_reserved_http")

        # Rule 4: the internal loopback rtl_tcp range.
        internal_range = range(
            self._internal_port_base, self._internal_port_base + self._max_devices
        )
        if proposed_port in internal_range or control_port in internal_range:
            return PortValidationResult(is_valid=False, rejection_code="port_reserved_internal")

        # Rule 5: the operator deny-list (`SENTRY_RESERVED_PORTS`).
        if (
            proposed_port in self._operator_reserved_ports
            or control_port in self._operator_reserved_ports
        ):
            return PortValidationResult(is_valid=False, rejection_code="port_reserved_operator")

        # Rule 6: an actual bind probe. Skipped only when the requesting
        # device already owns *this exact* pair — previously this compared
        # against "the device owns any pair at all", which meant moving an
        # already-configured device from one port to another (e.g.
        # 1234 -> 1300) skipped the probe for 1300 entirely, exactly the
        # case rule 6 exists to catch.
        already_owns_this_pair = own_pair is not None and own_pair[0] == proposed_port
        if not already_owns_this_pair:
            # Real `socket.bind()` calls are synchronous; offloaded so a
            # validation never blocks the event loop (and therefore every
            # open SSE stream) while probing.
            iq_bindable = await asyncio.to_thread(
                self._port_prober.is_bindable, "0.0.0.0", proposed_port
            )
            if not iq_bindable:
                return PortValidationResult(is_valid=False, rejection_code="port_in_use")
            control_bindable = await asyncio.to_thread(
                self._port_prober.is_bindable, "0.0.0.0", control_port
            )
            if not control_bindable:
                return PortValidationResult(is_valid=False, rejection_code="port_in_use")

        return PortValidationResult(is_valid=True, rejection_code=None)

    async def suggest_next(self) -> int | None:
        """Return a free port `>= DEFAULT_SUGGESTION_START_PORT` passing all six rules.

        Advisory only — the caller must still call `validate()` on whatever
        port is ultimately submitted. Fetches the reserved-pairs table once
        for the whole search (not once per candidate), steps by
        `SUGGESTION_PORT_STEP`, and stops after `MAX_SUGGESTION_ATTEMPTS`
        candidates or once the valid port range is exhausted, whichever
        comes first — see those constants for why.
        """
        reserved_pairs = await self._reserved_pairs()
        candidate_port = DEFAULT_SUGGESTION_START_PORT
        attempts = 0
        while candidate_port + 2 <= 65535 and attempts < MAX_SUGGESTION_ATTEMPTS:
            result = await self._validate_with_reserved_pairs(
                candidate_port, requesting_device_id=None, reserved_pairs=reserved_pairs
            )
            if result.is_valid:
                return candidate_port
            candidate_port += SUGGESTION_PORT_STEP
            attempts += 1
        return None

    async def _reserved_pairs(self) -> list[tuple[str, int, int]]:
        """Return `(device_id, output_port, control_port)` for every persisted device.

        Built from `list_all()` rather than the narrower
        `list_reserved_port_pairs()` because rule 2's `409 port_conflict`
        response must name the conflicting device (architecture §7.5), which
        requires the device's identity alongside its ports.
        """
        rows = await self._device_repository.list_all()
        return [
            (f"{row.identity_kind}:{row.identity_key}", row.output_port, row.output_port + 2)
            for row in rows
        ]
