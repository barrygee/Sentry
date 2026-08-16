"""Tests for `WiredShareService` — port selection, the uplink refusal, rollback.

These are the behaviours that decide whether an operator can still reach the Pi
after using this feature, so they are tested against `FakeWiredShareController`
rather than a real NetworkManager: the logic worth proving is entirely in the
service, and requiring a Linux host with root to prove it would mean it never
got proved at all.

The uplink refusal matters more here than in its hotspot equivalent. On the
target Pi the wired port *is* the uplink, so "would this drop the host's own
link" is the normal answer rather than the unusual one, and the acknowledgement
gate is the only thing standing between a save and a Pi nobody can reach.

Run with:  uv run pytest tests/wired
"""

from __future__ import annotations

import asyncio

import pytest

from app.backend.adapters.fake_wired_share import FakeWiredShareController
from app.backend.interfaces.types import HotspotClient, WiredInterface
from app.backend.interfaces.wired_share import (
    WiredShareCommandError,
    WiredShareTimeoutError,
    WiredShareUnavailableError,
)
from app.backend.services.event_bus import EventBus
from app.backend.services.wired_share import (
    WiredBusyError,
    WiredError,
    WiredShareService,
    WiredUnavailableError,
    WiredUplinkLossUnconfirmedError,
)
from tests.fakes.clock import FakeClock

WIRED_CONNECTION_NAME = "sentry-wired"
GATEWAY_CIDR = "10.10.10.1/24"
CONFIRM_TIMEOUT_S = 120.0


def _port(
    name: str = "eth0",
    *,
    active_connection_name: str | None = None,
    carries_default_route: bool = False,
    carrier_up: bool | None = True,
) -> WiredInterface:
    """One Ethernet port, varying only the fields the service actually reads."""
    return WiredInterface(
        name=name,
        mac_address="DC:A6:32:A9:DC:B0",
        state="connected" if active_connection_name else "disconnected",
        active_connection_name=active_connection_name,
        ipv4_addresses=("192.168.5.67/24",) if active_connection_name else (),
        carries_default_route=carries_default_route,
        carrier_up=carrier_up,
    )


def _service(
    controller: FakeWiredShareController,
    *,
    clock: FakeClock | None = None,
    configured_interface: str | None = None,
) -> WiredShareService:
    """Build the service under test with everything else faked."""
    resolved_clock = clock or FakeClock()
    return WiredShareService(
        controller=controller,
        event_bus=EventBus(resolved_clock),
        clock=resolved_clock,
        default_gateway_cidr=GATEWAY_CIDR,
        confirm_timeout_s=CONFIRM_TIMEOUT_S,
        configured_interface=configured_interface,
        wired_connection_name=WIRED_CONNECTION_NAME,
    )


class TestChoosingAPort:
    """Which Ethernet port a save lands on, and when it refuses to choose."""

    @pytest.mark.asyncio
    async def test_a_free_port_is_chosen_automatically(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)

        await service.apply_configuration(
            enabled=False, interface=None, gateway_cidr=None, confirm_uplink_loss=False
        )

        assert controller.recorded_applies[0].interface == "eth0"

    @pytest.mark.asyncio
    async def test_a_port_carrying_a_connection_is_never_chosen_automatically(self) -> None:
        """Automatic selection prefers the idle port over the busy one.

        The ordering matters, not just the outcome: `eth0` is listed first, so a
        naive "take the first port" would pick the uplink and refuse.
        """
        controller = FakeWiredShareController(
            interfaces=(
                _port("eth0", active_connection_name="Wired connection 1"),
                _port("eth1"),
            )
        )
        service = _service(controller)

        await service.apply_configuration(
            enabled=False, interface=None, gateway_cidr=None, confirm_uplink_loss=False
        )

        assert controller.recorded_applies[0].interface == "eth1"

    @pytest.mark.asyncio
    async def test_the_configured_port_is_used_when_the_request_names_none(self) -> None:
        """`SENTRY_WIRED_INTERFACE` is consulted before automatic selection."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"), _port("eth1")))
        service = _service(controller, configured_interface="eth1")

        await service.apply_configuration(
            enabled=False, interface=None, gateway_cidr=None, confirm_uplink_loss=False
        )

        assert controller.recorded_applies[0].interface == "eth1"

    @pytest.mark.asyncio
    async def test_the_request_wins_over_the_configured_port(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"), _port("eth1")))
        service = _service(controller, configured_interface="eth1")

        await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        assert controller.recorded_applies[0].interface == "eth0"

    @pytest.mark.asyncio
    async def test_a_host_with_no_ethernet_port_is_refused(self) -> None:
        service = _service(FakeWiredShareController(interfaces=()))

        with pytest.raises(WiredError) as raised:
            await service.apply_configuration(
                enabled=False, interface=None, gateway_cidr=None, confirm_uplink_loss=False
            )

        assert raised.value.code == "no_wired_interface"

    @pytest.mark.asyncio
    async def test_an_unknown_port_name_is_refused_and_lists_the_real_ones(self) -> None:
        """The available names ride along, so the UI can say what to pick instead."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)

        with pytest.raises(WiredError) as raised:
            await service.apply_configuration(
                enabled=False, interface="eth9", gateway_cidr=None, confirm_uplink_loss=False
            )

        assert raised.value.code == "interface_not_found"
        assert raised.value.context["available"] == ["eth0"]


class TestRefusingToDropTheUplink:
    """The gate that stops a save silently taking the Pi off the network."""

    @pytest.mark.asyncio
    async def test_an_active_connection_blocks_an_unconfirmed_save(self) -> None:
        controller = FakeWiredShareController(
            interfaces=(_port("eth0", active_connection_name="Wired connection 1"),)
        )
        service = _service(controller)

        with pytest.raises(WiredUplinkLossUnconfirmedError) as raised:
            await service.apply_configuration(
                enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
            )

        assert raised.value.code == "uplink_loss_unconfirmed"
        assert controller.recorded_applies == []

    @pytest.mark.asyncio
    async def test_a_default_route_blocks_an_unconfirmed_save(self) -> None:
        """Routing the host's traffic is an uplink even with no named profile."""
        controller = FakeWiredShareController(
            interfaces=(_port("eth0", carries_default_route=True),)
        )
        service = _service(controller)

        with pytest.raises(WiredUplinkLossUnconfirmedError):
            await service.apply_configuration(
                enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
            )

    @pytest.mark.asyncio
    async def test_the_acknowledgement_releases_the_gate(self) -> None:
        controller = FakeWiredShareController(
            interfaces=(_port("eth0", carries_default_route=True),)
        )
        service = _service(controller)

        snapshot = await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=True
        )

        assert snapshot.state.active is True

    @pytest.mark.asyncio
    async def test_automatic_selection_with_every_port_busy_still_refuses(self) -> None:
        """The single-port Pi's normal case: nothing free, so nothing is taken quietly."""
        controller = FakeWiredShareController(
            interfaces=(_port("eth0", carries_default_route=True),)
        )
        service = _service(controller)

        with pytest.raises(WiredUplinkLossUnconfirmedError) as raised:
            await service.apply_configuration(
                enabled=False, interface=None, gateway_cidr=None, confirm_uplink_loss=False
            )

        assert raised.value.context["interface"] == "eth0"

    @pytest.mark.asyncio
    async def test_our_own_share_is_not_reported_as_an_uplink(self) -> None:
        """The lesson the hotspot learned: our profile being up is not a link to lose.

        Treating any active connection as an uplink would show "sharing this
        port will disconnect it" *because* sharing had started.
        """
        controller = FakeWiredShareController(
            interfaces=(_port("eth0", active_connection_name=WIRED_CONNECTION_NAME),)
        )
        controller.state = controller.state.__class__(
            profile_exists=True,
            active=True,
            autoconnect=False,
            interface="eth0",
            gateway_cidr=GATEWAY_CIDR,
            activation_state="activated",
        )
        service = _service(controller)

        snapshot = await service.get_snapshot()

        assert snapshot.uplink_interface_is_share_interface is False

    @pytest.mark.asyncio
    async def test_a_default_route_counts_even_under_our_own_profile(self) -> None:
        """The narrower check must not become "ignore this port whenever we hold it"."""
        controller = FakeWiredShareController(
            interfaces=(
                _port(
                    "eth0",
                    active_connection_name=WIRED_CONNECTION_NAME,
                    carries_default_route=True,
                ),
            )
        )
        controller.state = controller.state.__class__(
            profile_exists=True,
            active=True,
            autoconnect=False,
            interface="eth0",
            gateway_cidr=GATEWAY_CIDR,
            activation_state="activated",
        )
        service = _service(controller)

        snapshot = await service.get_snapshot()

        assert snapshot.uplink_interface_is_share_interface is True


class TestTheCommitConfirmFlow:
    """The rollback timer, which is this feature's only real safety mechanism."""

    @pytest.mark.asyncio
    async def test_enabling_never_sets_autoconnect(self) -> None:
        """Surviving a reboot is earned by confirming, not by asking."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)

        snapshot = await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        assert snapshot.state.active is True
        assert snapshot.state.autoconnect is False
        assert snapshot.pending_confirmation is True
        await service.close()

    @pytest.mark.asyncio
    async def test_confirming_cancels_the_rollback_and_sets_autoconnect(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        clock = FakeClock()
        service = _service(controller, clock=clock)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        snapshot = await service.confirm()

        assert snapshot.state.autoconnect is True
        assert snapshot.pending_confirmation is False
        assert snapshot.confirm_deadline_ms is None

        # And the cancelled timer must not fire afterwards.
        clock.advance(CONFIRM_TIMEOUT_S * 2)
        await asyncio.sleep(0)
        assert controller.state.active is True

    @pytest.mark.asyncio
    async def test_an_unconfirmed_share_rolls_back_and_restores_the_previous_profile(
        self,
    ) -> None:
        """The whole point: a share nobody could reach puts the port back."""
        controller = FakeWiredShareController(
            interfaces=(_port("eth0", active_connection_name="Wired connection 1"),)
        )
        controller.active_connections["eth0"] = "Wired connection 1"
        clock = FakeClock()
        service = _service(controller, clock=clock)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=True
        )
        assert controller.state.active is True

        clock.advance(CONFIRM_TIMEOUT_S)
        # Two turns: one for the timer task to wake, one for its awaits to run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert controller.state.active is False
        assert controller.activated_names == ["Wired connection 1"]

    @pytest.mark.asyncio
    async def test_a_rollback_with_no_previous_profile_just_deactivates(self) -> None:
        """Nothing was recorded to restore, so nothing is invented to activate."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        clock = FakeClock()
        service = _service(controller, clock=clock)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        clock.advance(CONFIRM_TIMEOUT_S)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert controller.state.active is False
        assert controller.activated_names == []

    @pytest.mark.asyncio
    async def test_a_failing_rollback_is_swallowed_and_leaves_no_task(self) -> None:
        """This runs detached; a raised exception would vanish into the task."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        clock = FakeClock()
        service = _service(controller, clock=clock)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )
        controller.raise_on_next(
            WiredShareCommandError("nmcli exited 1", stderr_tail=None, exit_code=1)
        )

        clock.advance(CONFIRM_TIMEOUT_S)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        snapshot = await service.get_snapshot()
        assert snapshot.pending_confirmation is False

    @pytest.mark.asyncio
    async def test_confirming_with_nothing_on_trial_is_refused(self) -> None:
        service = _service(FakeWiredShareController(interfaces=(_port("eth0"),)))

        with pytest.raises(WiredError) as raised:
            await service.confirm()

        assert raised.value.code == "no_pending_confirmation"

    @pytest.mark.asyncio
    async def test_closing_cancels_the_timer_without_rolling_back(self) -> None:
        """A container restart must not tear down a working share."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        clock = FakeClock()
        service = _service(controller, clock=clock)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        await service.close()
        clock.advance(CONFIRM_TIMEOUT_S * 2)
        await asyncio.sleep(0)

        assert controller.state.active is True

    @pytest.mark.asyncio
    async def test_a_deadline_already_passed_rolls_back_without_a_second_window(self) -> None:
        """Sleeping toward the published deadline, not for a fresh duration."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        clock = FakeClock()
        service = _service(controller, clock=clock)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        clock.advance(CONFIRM_TIMEOUT_S * 3)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert controller.state.active is False


class TestEnablingAndDisabling:
    """The switch routes, which act without resending the configuration."""

    @pytest.mark.asyncio
    async def test_enabling_an_unconfigured_share_is_refused(self) -> None:
        service = _service(FakeWiredShareController(interfaces=(_port("eth0"),)))

        with pytest.raises(WiredError) as raised:
            await service.enable(confirm_uplink_loss=False)

        assert raised.value.code == "wired_not_configured"

    @pytest.mark.asyncio
    async def test_disabling_an_unconfigured_share_is_refused(self) -> None:
        service = _service(FakeWiredShareController(interfaces=(_port("eth0"),)))

        with pytest.raises(WiredError) as raised:
            await service.disable(confirm_uplink_loss=False)

        assert raised.value.code == "wired_not_configured"

    @pytest.mark.asyncio
    async def test_disabling_clears_autoconnect_as_well_as_stopping(self) -> None:
        """Stopping must also stop it coming back on the next boot."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )
        await service.confirm()
        assert controller.state.autoconnect is True

        snapshot = await service.disable(confirm_uplink_loss=False)

        assert snapshot.state.active is False
        assert snapshot.state.autoconnect is False

    @pytest.mark.asyncio
    async def test_saving_disabled_brings_an_active_share_down(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        snapshot = await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        assert snapshot.state.active is False
        assert snapshot.pending_confirmation is False


class TestTheProfileItself:
    """What actually gets written, which is short enough to assert whole."""

    @pytest.mark.asyncio
    async def test_the_default_gateway_is_used_when_the_request_names_none(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)

        await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        assert controller.recorded_applies[0].gateway_cidr == GATEWAY_CIDR

    @pytest.mark.asyncio
    async def test_a_named_gateway_overrides_the_default(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)

        await service.apply_configuration(
            enabled=False,
            interface="eth0",
            gateway_cidr="192.168.50.1/24",
            confirm_uplink_loss=False,
        )

        assert controller.recorded_applies[0].gateway_cidr == "192.168.50.1/24"

    @pytest.mark.asyncio
    async def test_forgetting_deactivates_before_deleting(self) -> None:
        """Deleting a live profile would leave the port serving DHCP with no owner."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        await service.forget()

        assert controller.deleted is True
        assert controller.state.active is False


class TestLeases:
    """Lease reads and releases, and the interface scoping that keeps them ours."""

    @pytest.mark.asyncio
    async def test_leases_are_scoped_to_the_shares_own_port(self) -> None:
        """Unscoped, a hotspot client would be listed here as a cabled machine."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),), clients=())
        service = _service(controller)
        await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        await service.list_clients()

        assert controller.lease_scopes == ["eth0"]

    @pytest.mark.asyncio
    async def test_an_unconfigured_share_reports_unknown_rather_than_borrowing(self) -> None:
        """`None` means "cannot tell" — never another interface's leases."""
        controller = FakeWiredShareController(clients=(_lease(),))
        service = _service(controller)

        assert await service.list_clients() is None

    @pytest.mark.asyncio
    async def test_releasing_pairs_the_mac_with_its_own_address(self) -> None:
        """The IP comes from the lease list, never from the caller."""
        controller = FakeWiredShareController(
            interfaces=(_port("eth0"),),
            clients=(_lease(mac="aa:bb:cc:dd:ee:01", ip="10.10.10.5"), _lease()),
        )
        service = _service(controller)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        await service.release_lease("AA:BB:CC:DD:EE:01")

        assert controller.released_leases == [("eth0", "10.10.10.5", "aa:bb:cc:dd:ee:01")]

    @pytest.mark.asyncio
    async def test_releasing_while_the_share_is_down_is_refused(self) -> None:
        """dnsmasq only exists while the shared connection is active."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),), clients=(_lease(),))
        service = _service(controller)
        await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        with pytest.raises(WiredError) as raised:
            await service.release_lease(_lease().mac_address)

        assert raised.value.code == "wired_not_running"

    @pytest.mark.asyncio
    async def test_releasing_an_unlisted_lease_is_refused(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0"),), clients=())
        service = _service(controller)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        with pytest.raises(WiredError) as raised:
            await service.release_lease("aa:bb:cc:dd:ee:ff")

        assert raised.value.code == "lease_not_found"

    @pytest.mark.asyncio
    async def test_releasing_with_an_unreadable_lease_file_is_refused(self) -> None:
        """`None` is "cannot tell", and must not be treated as an empty list."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),), clients=None)
        service = _service(controller)
        await service.apply_configuration(
            enabled=True, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        with pytest.raises(WiredError) as raised:
            await service.release_lease("aa:bb:cc:dd:ee:ff")

        assert raised.value.code == "leases_unreadable"


class TestDegradedHostsAndFailures:
    """What happens when the host cannot do this, or nmcli refuses."""

    @pytest.mark.asyncio
    async def test_a_snapshot_never_raises_on_an_unavailable_host(self) -> None:
        """`GET /api/wired` stays a 200 with `available: false`."""
        snapshot = await _service(FakeWiredShareController(available=False)).get_snapshot()

        assert snapshot.available is False
        assert snapshot.state.profile_exists is False

    @pytest.mark.asyncio
    async def test_every_mutation_is_refused_on_an_unavailable_host(self) -> None:
        service = _service(FakeWiredShareController(available=False))

        with pytest.raises(WiredUnavailableError):
            await service.apply_configuration(
                enabled=False, interface=None, gateway_cidr=None, confirm_uplink_loss=False
            )

    @pytest.mark.asyncio
    async def test_a_controller_unavailable_error_becomes_wired_unavailable(self) -> None:
        """Raised mid-operation rather than at the availability check."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        controller.raise_on_next(WiredShareUnavailableError("nmcli could not be started"))
        service = _service(controller)

        with pytest.raises(WiredUnavailableError) as raised:
            await service.apply_configuration(
                enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
            )

        assert raised.value.code == "wired_unavailable"

    @pytest.mark.asyncio
    async def test_a_command_failure_keeps_its_output_for_the_next_snapshot(self) -> None:
        """`stderr_tail` is the only thing that says why NetworkManager refused."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        controller.raise_on_next(
            WiredShareCommandError(
                "nmcli exited 1", stderr_tail="Error: unknown connection", exit_code=1
            )
        )
        service = _service(controller)

        with pytest.raises(WiredError) as raised:
            await service.apply_configuration(
                enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
            )
        assert raised.value.code == "wired_command_failed"

        snapshot = await service.get_snapshot()
        assert snapshot.last_error is not None
        assert snapshot.last_error[0] == "wired_command_failed"
        assert snapshot.last_error[3] == "Error: unknown connection"

    @pytest.mark.asyncio
    async def test_a_timeout_is_distinguished_from_a_plain_failure(self) -> None:
        """The operator's fix differs: a wedged NetworkManager, not a bad request."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        controller.raise_on_next(
            WiredShareTimeoutError("nmcli did not finish", stderr_tail=None, exit_code=None)
        )
        service = _service(controller)

        with pytest.raises(WiredError) as raised:
            await service.apply_configuration(
                enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
            )

        assert raised.value.code == "wired_command_timeout"

    @pytest.mark.asyncio
    async def test_a_second_concurrent_mutation_fails_fast_rather_than_queueing(self) -> None:
        """A queue of nmcli calls behind a wedged one is worse than a 409."""
        controller = FakeWiredShareController(interfaces=(_port("eth0"),))
        service = _service(controller)

        # Take the lock the way a mutation in flight would, then prove the next
        # caller is refused rather than parked behind it.
        await service._lock.acquire()  # noqa: SLF001 - the lock is the thing under test
        try:
            with pytest.raises(WiredBusyError) as raised:
                await service.enable(confirm_uplink_loss=False)
        finally:
            service._lock.release()  # noqa: SLF001

        assert raised.value.code == "wired_busy"


class TestTheCarrierReadout:
    """Whether a cable is plugged in — the wired-only signal, with three answers."""

    @pytest.mark.asyncio
    async def test_the_carrier_is_reported_from_the_shared_port(self) -> None:
        controller = FakeWiredShareController(interfaces=(_port("eth0", carrier_up=False),))
        service = _service(controller)
        await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        snapshot = await service.get_snapshot()

        assert snapshot.carrier_up is False

    @pytest.mark.asyncio
    async def test_an_unreported_carrier_stays_unknown_rather_than_false(self) -> None:
        """ "The host did not say" must never render as "nothing is plugged in"."""
        controller = FakeWiredShareController(interfaces=(_port("eth0", carrier_up=None),))
        service = _service(controller)
        await service.apply_configuration(
            enabled=False, interface="eth0", gateway_cidr=None, confirm_uplink_loss=False
        )

        snapshot = await service.get_snapshot()

        assert snapshot.carrier_up is None

    @pytest.mark.asyncio
    async def test_a_port_missing_from_the_listing_reports_nothing_rather_than_guessing(
        self,
    ) -> None:
        """A profile bound to a port that has since gone: unknown, not down."""
        controller = FakeWiredShareController(interfaces=())
        controller.state = controller.state.__class__(
            profile_exists=True,
            active=False,
            autoconnect=False,
            interface="eth9",
            gateway_cidr=GATEWAY_CIDR,
            activation_state=None,
        )
        service = _service(controller)

        snapshot = await service.get_snapshot()

        assert snapshot.carrier_up is None
        assert snapshot.uplink_interface_is_share_interface is False


def _lease(*, mac: str = "aa:bb:cc:dd:ee:ff", ip: str = "10.10.10.42") -> HotspotClient:
    """One DHCP lease, far enough in the future not to read as expired."""
    return HotspotClient(
        mac_address=mac,
        ip_address=ip,
        hostname="laptop",
        lease_expires_at_ms=4_000_000_000_000,
    )
