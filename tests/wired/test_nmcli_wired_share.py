"""Tests for `NmcliWiredShareController` — the argv it builds and the output it parses.

Everything here runs against `FakeProcessSpawner`, never a real `nmcli`. That is
the point of the adapter's shape: the argv is assembled by a pure method and the
output is parsed by pure functions, so the two things that can actually be wrong
— a missing property and a misread field — are provable with no NetworkManager,
no D-Bus and no root.

`modify_argv` is asserted as a whole property map rather than by spot-checking a
few keys. A property silently dropped from that list is exactly the kind of
change that leaves a share which comes up and does nothing useful.

Run with:  uv run pytest tests/wired
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from app.backend.adapters.nmcli_wired_share import (
    NmcliWiredShareController,
    UnavailableWiredShareController,
)
from app.backend.interfaces.process import ManagedProcess, ProcessSpawner
from app.backend.interfaces.types import WiredShareProfile
from app.backend.interfaces.wired_share import (
    WiredShareCommandError,
    WiredShareUnavailableError,
)

CONNECTION_NAME = "sentry-wired"
NMCLI_PATH = "/usr/bin/nmcli"


class _FinishedProcess:
    """A process that has already exited, with scripted output.

    The shape `tests/hotspot/test_nmcli_deactivate.py` established: the adapter
    only ever awaits `wait()` then `communicate()`, so a double that answers
    both immediately drives `_run` end to end with no event-loop choreography.
    """

    def __init__(self, exit_code: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.pid = 4242
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr

    @property
    def returncode(self) -> int | None:
        return self._exit_code

    async def wait(self) -> int:
        return self._exit_code

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def resume(self) -> None:
        pass

    async def communicate(self) -> tuple[bytes, bytes]:
        return (self._stdout, self._stderr)


class _ScriptedNmcli:
    """Hands back one scripted result per invocation, in order, recording each argv."""

    def __init__(self, *, spawn_error: Exception | None = None) -> None:
        self._results: list[_FinishedProcess] = []
        self._spawn_error = spawn_error
        self.commands: list[list[str]] = []
        """Every argv this spawner was asked for, minus nothing — the full list."""

    def script_output(self, stdout: bytes) -> None:
        """Queue a successful invocation returning `stdout`."""
        self._results.append(_FinishedProcess(0, stdout=stdout))

    def script_exit(self, exit_code: int, stderr: bytes = b"") -> None:
        """Queue an invocation exiting with `exit_code`."""
        self._results.append(_FinishedProcess(exit_code, stderr=stderr))

    async def spawn(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        name: str,
        capture_output: bool = False,
    ) -> ManagedProcess:
        if self._spawn_error is not None:
            raise self._spawn_error
        self.commands.append(list(argv))
        if not self._results:
            raise AssertionError(f"unscripted nmcli invocation: {list(argv)}")
        return cast(ManagedProcess, self._results.pop(0))


def _controller(
    spawner: _ScriptedNmcli, nm_state_root: Path | None = None
) -> NmcliWiredShareController:
    return NmcliWiredShareController(
        process_spawner=cast(ProcessSpawner, spawner),
        nmcli_path=NMCLI_PATH,
        connection_name=CONNECTION_NAME,
        nm_state_root=nm_state_root or Path("/nonexistent"),
        timeout_s=5.0,
    )


def _profile(
    *, interface: str = "eth0", gateway_cidr: str = "10.10.10.1/24", autoconnect: bool = False
) -> WiredShareProfile:
    return WiredShareProfile(
        gateway_cidr=gateway_cidr, interface=interface, autoconnect=autoconnect
    )


def _properties(argv: list[str]) -> dict[str, str]:
    """Read the `key value key value` tail of a `connection modify` argv."""
    tail = argv[3:]
    return dict(zip(tail[::2], tail[1::2], strict=True))


class TestTheModifyArgv:
    """What actually gets written to the profile."""

    def test_the_whole_property_set_is_written(self) -> None:
        """Asserted whole: a dropped property is the failure mode worth catching."""
        argv = _controller(_ScriptedNmcli()).modify_argv(_profile())

        assert argv[:3] == ["connection", "modify", CONNECTION_NAME]
        assert _properties(argv) == {
            "connection.interface-name": "eth0",
            "connection.autoconnect": "no",
            "ipv4.method": "shared",
            "ipv4.addresses": "10.10.10.1/24",
            "ipv4.never-default": "yes",
            "ipv6.method": "ignore",
        }

    def test_shared_mode_is_what_starts_the_dhcp_server(self) -> None:
        """`ipv4.method shared` is the entire feature; nothing else serves DHCP."""
        argv = _controller(_ScriptedNmcli()).modify_argv(_profile())

        assert _properties(argv)["ipv4.method"] == "shared"

    def test_never_default_is_set_so_sharing_cannot_steal_the_default_route(self) -> None:
        """Without it, NetworkManager can prefer the share's own gateway.

        That would take a Pi which still has an uplink off the internet in order
        to serve one cable — the opposite of what "additive" is supposed to mean.
        """
        argv = _controller(_ScriptedNmcli()).modify_argv(_profile())

        assert _properties(argv)["ipv4.never-default"] == "yes"

    def test_autoconnect_is_rendered_the_way_nmcli_expects(self) -> None:
        controller = _controller(_ScriptedNmcli())

        assert (
            _properties(controller.modify_argv(_profile(autoconnect=True)))[
                "connection.autoconnect"
            ]
            == "yes"
        )
        assert (
            _properties(controller.modify_argv(_profile(autoconnect=False)))[
                "connection.autoconnect"
            ]
            == "no"
        )

    def test_no_argv_element_carries_a_secret(self) -> None:
        """There is no passphrase in this feature, so nothing here can leak one."""
        argv = _controller(_ScriptedNmcli()).modify_argv(_profile())

        assert not any("psk" in element or "password" in element for element in argv)

    @pytest.mark.asyncio
    async def test_a_missing_profile_is_created_before_it_is_modified(self) -> None:
        spawner = _ScriptedNmcli()
        # `read_state` runs first and must report the profile as absent, which
        # nmcli signals with a non-zero exit rather than empty output.
        spawner.script_exit(1)
        spawner.script_exit(0)
        spawner.script_exit(0)

        await _controller(spawner).apply_profile(_profile())

        commands = [command[1:] for command in spawner.commands]
        assert commands[1][:4] == ["connection", "add", "type", "ethernet"]
        assert commands[2][:2] == ["connection", "modify"]

    @pytest.mark.asyncio
    async def test_an_existing_profile_is_modified_without_being_re_added(self) -> None:
        """Re-adding would create a second profile Sentry does not own."""
        spawner = _ScriptedNmcli()
        spawner.script_output(b"connection.id:sentry-wired\nGENERAL.STATE:activated\n")
        spawner.script_exit(0)

        await _controller(spawner).apply_profile(_profile())

        commands = [command[1:] for command in spawner.commands]
        assert not any(command[:2] == ["connection", "add"] for command in commands)


class TestReadingState:
    """`read_state`, which reports reality rather than a remembered write."""

    @pytest.mark.asyncio
    async def test_a_missing_profile_reads_as_absent_rather_than_failing(self) -> None:
        """nmcli exits non-zero for "no such connection", the ordinary state."""
        spawner = _ScriptedNmcli()
        spawner.script_exit(1)

        state = await _controller(spawner).read_state()

        assert state.profile_exists is False
        assert state.interface is None
        assert state.gateway_cidr is None

    @pytest.mark.asyncio
    async def test_empty_output_also_reads_as_absent(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_output(b"")

        assert (await _controller(spawner).read_state()).profile_exists is False

    @pytest.mark.asyncio
    async def test_a_live_profile_is_read_back_field_by_field(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_output(
            b"connection.id:sentry-wired\n"
            b"connection.interface-name:eth0\n"
            b"connection.autoconnect:yes\n"
            b"ipv4.method:shared\n"
            b"ipv4.addresses:10.10.10.1/24\n"
            b"GENERAL.STATE:activated\n"
        )

        state = await _controller(spawner).read_state()

        assert state.profile_exists is True
        assert state.active is True
        assert state.autoconnect is True
        assert state.interface == "eth0"
        assert state.gateway_cidr == "10.10.10.1/24"

    @pytest.mark.asyncio
    async def test_a_configured_but_stopped_profile_is_not_active(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_output(
            b"connection.id:sentry-wired\n"
            b"connection.interface-name:eth0\n"
            b"connection.autoconnect:no\n"
            b"ipv4.addresses:10.10.10.1/24\n"
        )

        state = await _controller(spawner).read_state()

        assert state.profile_exists is True
        assert state.active is False
        assert state.autoconnect is False


class TestListingPorts:
    """`list_wired_interfaces`, and the carrier field only a cable has."""

    @pytest.mark.asyncio
    async def test_only_ethernet_devices_are_listed(self) -> None:
        """A radio in the wired picker would be a port an operator cannot use."""
        spawner = _ScriptedNmcli()
        spawner.script_output(
            b"eth0:ethernet:connected:Wired connection 1\n"
            b"wlan0:wifi:connected:house-wifi\n"
            b"lo:loopback:unmanaged:\n"
        )
        spawner.script_output(b"GENERAL.STATE:connected\nWIRED-PROPERTIES.CARRIER:on\n")

        interfaces = await _controller(spawner).list_wired_interfaces()

        assert [entry.name for entry in interfaces] == ["eth0"]

    @pytest.mark.asyncio
    async def test_the_carrier_is_read_from_nmclis_on_off_wording(self) -> None:
        """nmcli prints on/off here, not yes/no — a yes/no-only parse reads False."""
        spawner = _ScriptedNmcli()
        spawner.script_output(b"eth0:ethernet:connected:Wired connection 1\n")
        spawner.script_output(
            b"GENERAL.STATE:connected\n"
            b"GENERAL.HWADDR:DC:A6:32:A9:DC:B0\n"
            b"IP4.ADDRESS[1]:192.168.5.67/24\n"
            b"IP4.GATEWAY:192.168.5.1\n"
            b"WIRED-PROPERTIES.CARRIER:on\n"
        )

        interfaces = await _controller(spawner).list_wired_interfaces()

        assert interfaces[0].carrier_up is True
        assert interfaces[0].carries_default_route is True
        assert interfaces[0].ipv4_addresses == ("192.168.5.67/24",)
        # The escaped colons in the MAC must survive the terse split intact.
        assert interfaces[0].mac_address == "DC:A6:32:A9:DC:B0"

    @pytest.mark.asyncio
    async def test_an_unplugged_port_reports_the_carrier_down(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_output(b"eth0:ethernet:disconnected:\n")
        spawner.script_output(b"GENERAL.STATE:disconnected\nWIRED-PROPERTIES.CARRIER:off\n")

        interfaces = await _controller(spawner).list_wired_interfaces()

        assert interfaces[0].carrier_up is False
        assert interfaces[0].active_connection_name is None

    @pytest.mark.asyncio
    async def test_an_unreported_carrier_is_unknown_rather_than_down(self) -> None:
        """Absent means this nmcli did not say, which is not "nothing plugged in"."""
        spawner = _ScriptedNmcli()
        spawner.script_output(b"eth0:ethernet:connected:Wired connection 1\n")
        spawner.script_output(b"GENERAL.STATE:connected\n")

        interfaces = await _controller(spawner).list_wired_interfaces()

        assert interfaces[0].carrier_up is None

    @pytest.mark.asyncio
    async def test_a_port_that_cannot_be_described_still_appears(self) -> None:
        """A port missing from the picker is worse than one described sparsely."""
        spawner = _ScriptedNmcli()
        spawner.script_output(b"eth0:ethernet:connected:Wired connection 1\n")
        spawner.script_exit(1)

        interfaces = await _controller(spawner).list_wired_interfaces()

        assert [entry.name for entry in interfaces] == ["eth0"]
        assert interfaces[0].carrier_up is None
        assert interfaces[0].active_connection_name == "Wired connection 1"

    @pytest.mark.asyncio
    async def test_a_failing_enumeration_returns_nothing_rather_than_raising(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_exit(1)

        assert await _controller(spawner).list_wired_interfaces() == ()


class TestAvailability:
    """`is_available` must never raise — every degraded path asks it first."""

    @pytest.mark.asyncio
    async def test_a_running_networkmanager_is_available(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_output(b"running\n")

        assert await _controller(spawner).is_available() is True

    @pytest.mark.asyncio
    async def test_a_stopped_networkmanager_is_not_available(self) -> None:
        """`stopped` is what nmcli actually prints, so that is what is asserted."""
        spawner = _ScriptedNmcli()
        spawner.script_output(b"stopped\n")

        assert await _controller(spawner).is_available() is False

    @pytest.mark.asyncio
    async def test_a_failing_nmcli_answers_false_rather_than_raising(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_exit(127)

        assert await _controller(spawner).is_available() is False


class TestDeactivation:
    """Bringing the share down, which has to be idempotent."""

    @pytest.mark.asyncio
    async def test_an_already_stopped_share_is_not_an_error(self) -> None:
        """nmcli calls this a failure; the postcondition is already satisfied.

        The hotspot learned this the hard way — saving with the network switched
        off wrote the profile and then reported a 500.
        """
        spawner = _ScriptedNmcli()
        spawner.script_exit(1)  # connection down: "not an active connection"
        spawner.script_output(b"connection.id:sentry-wired\n")  # read_state: not active

        await _controller(spawner).deactivate()

    @pytest.mark.asyncio
    async def test_a_genuine_failure_to_stop_a_live_share_still_raises(self) -> None:
        """That one leaves the Pi's uplink port serving DHCP; it must surface."""
        spawner = _ScriptedNmcli()
        spawner.script_exit(1)
        spawner.script_output(b"connection.id:sentry-wired\nGENERAL.STATE:activated\n")

        with pytest.raises(WiredShareCommandError):
            await _controller(spawner).deactivate()


class TestCommandFailures:
    """How a failing command reaches an operator."""

    @pytest.mark.asyncio
    async def test_stderr_is_kept_and_bounded(self) -> None:
        spawner = _ScriptedNmcli()
        spawner.script_exit(1, stderr=b"x" * 900)

        with pytest.raises(WiredShareCommandError) as raised:
            await _controller(spawner).activate()

        assert raised.value.stderr_tail is not None
        assert len(raised.value.stderr_tail) == 400
        assert raised.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_an_unspawnable_nmcli_is_unavailable_not_a_command_failure(self) -> None:
        """Nothing is broken — the capability simply is not on this host."""
        spawner = _ScriptedNmcli(spawn_error=OSError("No such file or directory"))

        with pytest.raises(WiredShareUnavailableError):
            await _controller(spawner).activate()


class TestTheUnavailableController:
    """The null object used on a host with no nmcli or no D-Bus socket."""

    @pytest.mark.asyncio
    async def test_reads_degrade_rather_than_raising(self) -> None:
        controller = UnavailableWiredShareController("no nmcli")

        assert await controller.is_available() is False
        assert await controller.list_wired_interfaces() == ()
        assert (await controller.read_state()).profile_exists is False
        assert await controller.active_connection_on("eth0") is None

    @pytest.mark.asyncio
    async def test_every_mutation_is_refused(self) -> None:
        controller = UnavailableWiredShareController("no nmcli")

        with pytest.raises(WiredShareUnavailableError):
            await controller.apply_profile(_profile())
        with pytest.raises(WiredShareUnavailableError):
            await controller.activate()
        with pytest.raises(WiredShareUnavailableError):
            await controller.deactivate()
        with pytest.raises(WiredShareUnavailableError):
            await controller.set_autoconnect(True)
        with pytest.raises(WiredShareUnavailableError):
            await controller.delete_profile()
        with pytest.raises(WiredShareUnavailableError):
            await controller.activate_named("other")
        with pytest.raises(WiredShareUnavailableError):
            await controller.release_lease("eth0", "10.10.10.5", "aa:bb:cc:dd:ee:ff")

    def test_leases_are_unknown_with_no_state_root(self) -> None:
        assert UnavailableWiredShareController("no nmcli").list_clients() is None

    def test_leases_are_still_read_when_a_state_root_is_known(self, tmp_path: Path) -> None:
        """A plain file read needs no NetworkManager, so it is not thrown away."""
        (tmp_path / "dnsmasq-eth0.leases").write_text(
            "4000000000 aa:bb:cc:dd:ee:ff 10.10.10.42 laptop *\n", encoding="utf-8"
        )
        controller = UnavailableWiredShareController("no nmcli", nm_state_root=tmp_path)

        clients = controller.list_clients("eth0")

        assert clients is not None
        assert clients[0].ip_address == "10.10.10.42"
