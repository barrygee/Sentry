"""Validate and reserve `(P, P+2)` port pairs (architecture §8).

Pure rule evaluation plus one optional bind probe. Never picks a port
unasked — it validates an operator's choice and *suggests* a next free one;
auto-assignment was rejected because the port is part of Sentinel's stored
configuration (architecture §8 intro).
"""

from __future__ import annotations

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
"""The lowest port `suggest_next()` considers, yielding 1234, 1238, 1242… by default."""


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
        control_port = proposed_port + 2

        # Rule 1: range. `P + 2` must not exceed 65535, and `P` itself must
        # leave room for `P + 2` to stay a valid 16-bit port.
        if proposed_port < 1024 or control_port > 65535:
            return PortValidationResult(is_valid=False, rejection_code="port_out_of_range")

        # Rule 2: collision with another device's reserved pair — including
        # disabled and absent devices, whose reservations still block a new
        # assignment. `requesting_device_id` exempts a device re-saving its
        # own current port.
        for other_device_id, other_port, other_control_port in await self._reserved_pairs():
            if other_device_id == requesting_device_id:
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

        # Rule 6: an actual bind probe. Not evaluated against a device's own
        # already-running pair, since that port is legitimately held by this
        # request's own process right now.
        if requesting_device_id is None:
            already_owns_pair = False
        else:
            already_owns_pair = any(
                other_device_id == requesting_device_id
                for other_device_id, _, _ in await self._reserved_pairs()
            )
        if not already_owns_pair:
            if not self._port_prober.is_bindable("0.0.0.0", proposed_port):
                return PortValidationResult(is_valid=False, rejection_code="port_in_use")
            if not self._port_prober.is_bindable("0.0.0.0", control_port):
                return PortValidationResult(is_valid=False, rejection_code="port_in_use")

        return PortValidationResult(is_valid=True, rejection_code=None)

    async def suggest_next(self) -> int | None:
        """Return the lowest port `>= DEFAULT_SUGGESTION_START_PORT` passing all six rules.

        Advisory only — the caller must still call `validate()` on whatever
        port is ultimately submitted. Bounded by the valid port range so a
        fully-packed allocation terminates with `None` rather than looping
        forever.
        """
        candidate_port = DEFAULT_SUGGESTION_START_PORT
        while candidate_port + 2 <= 65535:
            result = await self.validate(candidate_port, requesting_device_id=None)
            if result.is_valid:
                return candidate_port
            candidate_port += 1
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
