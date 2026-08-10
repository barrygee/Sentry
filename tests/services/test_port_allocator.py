"""Tests for the six port-assignment rules and the suggestion search (architecture §8).

Every rejection here is one an operator can hit from the UI, and each rule exists
because of a distinct failure: a port outside the usable range, a pair that
overlaps another dongle's, the console's own HTTP port, the internal loopback
range the relays use, the operator's deny-list, and a port something else on the
Pi has already bound.

Two of these are regression tests for bugs the code comments record rather than
for rules in the architecture:

* moving an already-configured device to a *different* port must still be bind
  probed — the check used to be "does this device own any pair", which skipped
  the probe in exactly the case rule 6 exists for;
* `suggest_next()` must fetch the reserved pairs once per search, not once per
  candidate, which on a dense allocation was thousands of round-trips.

Run with:  uv run pytest tests/services/test_port_allocator.py
"""

from __future__ import annotations

import pytest

from app.backend.interfaces.netprobe import PortProber
from app.backend.interfaces.repository import DeviceRepository
from app.backend.services import port_allocator as port_allocator_module
from app.backend.services.port_allocator import (
    MAX_SUGGESTION_ATTEMPTS,
    SUGGESTION_PORT_STEP,
    PortAllocatorService,
)

from .fakes import FakeDeviceRepository, FakePortProber, device_row

HTTP_PORT = 8000
INTERNAL_PORT_BASE = 5000
MAX_DEVICES = 4
"""So the internal loopback range is 5000-5003 inclusive."""


def build_allocator(
    *,
    repository: FakeDeviceRepository | None = None,
    prober: FakePortProber | None = None,
    operator_reserved_ports: frozenset[int] = frozenset(),
) -> PortAllocatorService:
    return PortAllocatorService(
        port_prober=prober or FakePortProber(),
        device_repository=repository or FakeDeviceRepository(),
        http_port=HTTP_PORT,
        internal_port_base=INTERNAL_PORT_BASE,
        max_devices=MAX_DEVICES,
        operator_reserved_ports=operator_reserved_ports,
    )


def test_the_fakes_satisfy_the_protocols() -> None:
    """Guards the fakes themselves: a drifted seam would make every test below vacuous."""
    assert isinstance(FakePortProber(), PortProber)
    assert isinstance(FakeDeviceRepository(), DeviceRepository)


class TestRule1Range:
    @pytest.mark.asyncio
    async def test_accepts_a_free_port_in_range(self) -> None:
        result = await build_allocator().validate(1234, requesting_device_id=None)

        assert result.is_valid is True
        assert result.rejection_code is None

    @pytest.mark.asyncio
    async def test_rejects_a_privileged_port(self) -> None:
        result = await build_allocator().validate(1023, requesting_device_id=None)

        assert result.is_valid is False
        assert result.rejection_code == "port_out_of_range"

    @pytest.mark.asyncio
    async def test_accepts_the_lowest_unprivileged_port(self) -> None:
        """1024 is the boundary the rule allows — one below is the rejection above."""
        result = await build_allocator().validate(1024, requesting_device_id=None)

        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_rejects_a_port_whose_control_port_would_overflow(self) -> None:
        """65534 is in range itself; its control port, 65536, is not."""
        result = await build_allocator().validate(65534, requesting_device_id=None)

        assert result.is_valid is False
        assert result.rejection_code == "port_out_of_range"

    @pytest.mark.asyncio
    async def test_accepts_the_highest_port_whose_pair_still_fits(self) -> None:
        result = await build_allocator().validate(65533, requesting_device_id=None)

        assert result.is_valid is True


class TestRule2Conflicts:
    @pytest.mark.asyncio
    async def test_rejects_a_port_another_device_holds_and_names_it(self) -> None:
        repository = FakeDeviceRepository([device_row(identity_key="AIS-01", output_port=1234)])

        result = await build_allocator(repository=repository).validate(
            1234, requesting_device_id=None
        )

        assert result.is_valid is False
        assert result.rejection_code == "port_conflict"
        # Named, because the 409 has to tell the operator *which* device (§7.5).
        assert result.conflicts_with == "serial:AIS-01"

    @pytest.mark.asyncio
    async def test_rejects_a_port_that_lands_on_another_devices_control_port(self) -> None:
        """1236 is free as an output port but is 1234's control port."""
        repository = FakeDeviceRepository([device_row(output_port=1234)])

        result = await build_allocator(repository=repository).validate(
            1236, requesting_device_id=None
        )

        assert result.rejection_code == "port_conflict"

    @pytest.mark.asyncio
    async def test_rejects_a_port_whose_control_port_hits_another_devices_output(self) -> None:
        """1232's control port is 1234, which the other device already holds."""
        repository = FakeDeviceRepository([device_row(output_port=1234)])

        result = await build_allocator(repository=repository).validate(
            1232, requesting_device_id=None
        )

        assert result.rejection_code == "port_conflict"

    @pytest.mark.asyncio
    async def test_a_disabled_devices_reservation_still_blocks(self) -> None:
        """Disabled is not released: re-enabling must never find its port taken."""
        repository = FakeDeviceRepository([device_row(output_port=1234, enabled=False)])

        result = await build_allocator(repository=repository).validate(
            1234, requesting_device_id=None
        )

        assert result.rejection_code == "port_conflict"

    @pytest.mark.asyncio
    async def test_a_device_may_resave_its_own_current_port(self) -> None:
        repository = FakeDeviceRepository([device_row(identity_key="AIS-01", output_port=1234)])

        result = await build_allocator(repository=repository).validate(
            1234, requesting_device_id="serial:AIS-01"
        )

        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_a_device_still_collides_with_a_different_devices_port(self) -> None:
        """The exemption is for the requester's own pair only, not a blanket pass."""
        repository = FakeDeviceRepository(
            [
                device_row(record_id=1, identity_key="AIS-01", output_port=1234),
                device_row(record_id=2, identity_key="ADSB-01", output_port=1240),
            ]
        )

        result = await build_allocator(repository=repository).validate(
            1240, requesting_device_id="serial:AIS-01"
        )

        assert result.rejection_code == "port_conflict"
        assert result.conflicts_with == "serial:ADSB-01"


class TestRules3To5ReservedRanges:
    @pytest.mark.asyncio
    async def test_rejects_the_http_port(self) -> None:
        result = await build_allocator().validate(HTTP_PORT, requesting_device_id=None)

        assert result.rejection_code == "port_reserved_http"

    @pytest.mark.asyncio
    async def test_rejects_a_port_whose_control_port_is_the_http_port(self) -> None:
        result = await build_allocator().validate(HTTP_PORT - 2, requesting_device_id=None)

        assert result.rejection_code == "port_reserved_http"

    @pytest.mark.asyncio
    async def test_rejects_the_internal_loopback_range(self) -> None:
        result = await build_allocator().validate(INTERNAL_PORT_BASE, requesting_device_id=None)

        assert result.rejection_code == "port_reserved_internal"

    @pytest.mark.asyncio
    async def test_rejects_the_last_port_of_the_internal_range(self) -> None:
        """The range is `base` to `base + max_devices - 1`; this is its top."""
        last_internal_port = INTERNAL_PORT_BASE + MAX_DEVICES - 1

        result = await build_allocator().validate(last_internal_port, requesting_device_id=None)

        assert result.rejection_code == "port_reserved_internal"

    @pytest.mark.asyncio
    async def test_accepts_the_port_just_past_the_internal_range(self) -> None:
        """Off-by-one guard: `base + max_devices` is outside the range, not the last of it."""
        just_past = INTERNAL_PORT_BASE + MAX_DEVICES

        result = await build_allocator().validate(just_past, requesting_device_id=None)

        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_rejects_an_operator_denied_port(self) -> None:
        allocator = build_allocator(operator_reserved_ports=frozenset({1300}))

        result = await allocator.validate(1300, requesting_device_id=None)

        assert result.rejection_code == "port_reserved_operator"

    @pytest.mark.asyncio
    async def test_rejects_a_pair_whose_control_port_is_operator_denied(self) -> None:
        allocator = build_allocator(operator_reserved_ports=frozenset({1302}))

        result = await allocator.validate(1300, requesting_device_id=None)

        assert result.rejection_code == "port_reserved_operator"


class TestRule6BindProbe:
    @pytest.mark.asyncio
    async def test_rejects_a_port_already_bound_on_the_host(self) -> None:
        prober = FakePortProber(unbindable_ports=frozenset({1234}))

        result = await build_allocator(prober=prober).validate(1234, requesting_device_id=None)

        assert result.rejection_code == "port_in_use"

    @pytest.mark.asyncio
    async def test_rejects_when_only_the_control_port_is_bound(self) -> None:
        """The pair is reserved as a unit — a free 1234 with a taken 1236 is unusable."""
        prober = FakePortProber(unbindable_ports=frozenset({1236}))

        result = await build_allocator(prober=prober).validate(1234, requesting_device_id=None)

        assert result.rejection_code == "port_in_use"
        assert prober.probed_ports == [1234, 1236]

    @pytest.mark.asyncio
    async def test_does_not_probe_the_control_port_once_the_iq_port_has_failed(self) -> None:
        """Rules return on first failure; a second probe would be wasted work."""
        prober = FakePortProber(unbindable_ports=frozenset({1234, 1236}))

        await build_allocator(prober=prober).validate(1234, requesting_device_id=None)

        assert prober.probed_ports == [1234]

    @pytest.mark.asyncio
    async def test_skips_the_probe_when_the_device_already_owns_this_exact_pair(self) -> None:
        """A running device holds its own port open; probing it would reject it."""
        repository = FakeDeviceRepository([device_row(identity_key="AIS-01", output_port=1234)])
        prober = FakePortProber(unbindable_ports=frozenset({1234, 1236}))

        result = await build_allocator(repository=repository, prober=prober).validate(
            1234, requesting_device_id="serial:AIS-01"
        )

        assert result.is_valid is True
        assert prober.probed_ports == []

    @pytest.mark.asyncio
    async def test_still_probes_when_a_configured_device_moves_to_a_new_port(self) -> None:
        """The regression the comment on rule 6 records.

        The skip used to trigger on "this device owns *a* pair", so moving a
        device from 1234 to 1300 skipped the probe for 1300 — precisely the case
        the bind probe exists to catch, and the only one where the operator is
        choosing a port they have never used.
        """
        repository = FakeDeviceRepository([device_row(identity_key="AIS-01", output_port=1234)])
        prober = FakePortProber(unbindable_ports=frozenset({1300}))

        result = await build_allocator(repository=repository, prober=prober).validate(
            1300, requesting_device_id="serial:AIS-01"
        )

        assert result.is_valid is False
        assert result.rejection_code == "port_in_use"
        assert prober.probed_ports == [1300]


class TestSuggestNext:
    @pytest.mark.asyncio
    async def test_suggests_the_default_start_port_on_an_empty_console(self) -> None:
        assert await build_allocator().suggest_next() == 1234

    @pytest.mark.asyncio
    async def test_steps_past_a_taken_pair(self) -> None:
        repository = FakeDeviceRepository([device_row(output_port=1234)])

        assert await build_allocator(repository=repository).suggest_next() == 1234 + (
            SUGGESTION_PORT_STEP
        )

    @pytest.mark.asyncio
    async def test_steps_repeatedly_over_a_dense_allocation(self) -> None:
        repository = FakeDeviceRepository(
            [
                device_row(record_id=1, identity_key="A", output_port=1234),
                device_row(record_id=2, identity_key="B", output_port=1238),
                device_row(record_id=3, identity_key="C", output_port=1242),
            ]
        )

        assert await build_allocator(repository=repository).suggest_next() == 1246

    @pytest.mark.asyncio
    async def test_skips_a_port_the_host_has_bound(self) -> None:
        prober = FakePortProber(unbindable_ports=frozenset({1234}))

        assert await build_allocator(prober=prober).suggest_next() == 1238

    @pytest.mark.asyncio
    async def test_fetches_the_reserved_pairs_once_for_the_whole_search(self) -> None:
        """The performance contract, and the reason `_validate_with_reserved_pairs` exists.

        Each candidate used to re-read the table. On a dense allocation that was
        thousands of round-trips for one `GET /api/devices`, so the count — not
        just the answer — is the thing under test.
        """
        repository = FakeDeviceRepository(
            [
                device_row(record_id=index, identity_key=f"D{index}", output_port=1234 + index * 4)
                for index in range(20)
            ]
        )

        await build_allocator(repository=repository).suggest_next()

        assert repository.list_all_call_count == 1

    @pytest.mark.asyncio
    async def test_gives_up_rather_than_searching_forever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing is bindable, so every candidate fails and the cap is what stops it."""
        monkeypatch.setattr(port_allocator_module, "MAX_SUGGESTION_ATTEMPTS", 5)
        prober = FakePortProber(unbindable_ports=frozenset(range(1024, 65536)))

        assert await build_allocator(prober=prober).suggest_next() is None
        # Capped, not merely unlucky: five candidates tried, one probe each.
        assert prober.probed_ports == [1234, 1238, 1242, 1246, 1250]

    @pytest.mark.asyncio
    async def test_stops_at_the_top_of_the_port_range(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other exit: the range runs out before the attempt cap does."""
        monkeypatch.setattr(port_allocator_module, "DEFAULT_SUGGESTION_START_PORT", 65530)
        prober = FakePortProber(unbindable_ports=frozenset(range(1024, 65536)))

        assert await build_allocator(prober=prober).suggest_next() is None
        # 65530 is the only candidate whose control port still fits under 65535.
        assert prober.probed_ports == [65530]

    def test_the_attempt_cap_is_low_enough_to_bound_one_request(self) -> None:
        """The cap only helps if it is small; 2000 candidates is the documented ceiling."""
        assert MAX_SUGGESTION_ATTEMPTS <= 2_000


class TestReservedPairs:
    @pytest.mark.asyncio
    async def test_builds_device_ids_from_identity_kind_and_key(self) -> None:
        """`usb:` identities conflict-report the same way `serial:` ones do."""
        repository = FakeDeviceRepository(
            [device_row(identity_kind="usb", identity_key="1-1.2", output_port=1234)]
        )

        result = await build_allocator(repository=repository).validate(
            1234, requesting_device_id=None
        )

        assert result.conflicts_with == "usb:1-1.2"
