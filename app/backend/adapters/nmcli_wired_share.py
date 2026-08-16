"""Real `WiredShareController` driving NetworkManager through `nmcli` (ADR-0014).

The wired twin of `nmcli_wifi_ap.py`, and it shares that module's disciplines
verbatim: every command is a fully-formed list argv through `ProcessSpawner`
with no shell anywhere, and all output parsing lives in the pure functions of
`adapters/nmcli_parsing.py` rather than being re-implemented here.

What it does *not* share is a secret. A wired share is `ipv4.method shared` on
an Ethernet port and nothing else — no key management, no passphrase, no
`--show-secrets` to carefully avoid. That is why `_run` here takes no `secret`
argument and why nothing in this file redacts anything: there is no value that
could need it, and a redaction path with no secret to redact is a claim this
module should not be making.

On a host with no `nmcli` or no NetworkManager, construction still succeeds but
`is_available()` answers False and every mutator raises
`WiredShareUnavailableError`, which is what lets `GET /api/wired` stay a 200.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from app.backend.adapters.nmcli_parsing import (
    STDERR_TRUNCATE_CHARS,
    collect_indexed_property,
    parse_active_connections,
    parse_device_status,
    parse_property_rows,
    parse_yes_no,
    read_dnsmasq_leases,
    yes_no,
)
from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.types import (
    HotspotClient,
    WiredInterface,
    WiredShareProfile,
    WiredShareRuntimeState,
)
from app.backend.interfaces.wired_share import (
    WiredShareCommandError,
    WiredShareTimeoutError,
    WiredShareUnavailableError,
)

_logger = logging.getLogger(__name__)

_FALLBACK_SPAWN_PATH = "/usr/local/bin:/usr/bin:/bin"

_DHCP_RELEASE_PATH = "/usr/bin/dhcp_release"
"""From `dnsmasq-utils`, installed in the runtime image. An absolute path for
the same reason `nmcli`'s is: a bare name would be resolved against `PATH`."""

_ETHERNET_DEVICE_TYPE = "ethernet"
"""The `TYPE` column value `nmcli device status` prints for a wired port.

USB Ethernet adapters report this too, which is the point: a second port on a
dongle is the one configuration where sharing costs the Pi nothing, and it must
appear in the picker alongside the built-in one.
"""


class NmcliWiredShareController:
    """Drives one NetworkManager wired-sharing profile through the `nmcli` binary.

    `nm_state_root` is injected rather than hard-coded — production passes
    `/var/lib/NetworkManager`, tests point it at a fixture directory — the same
    root-parameterisation discipline `NmcliWifiApController`, `SysfsUsbDiscovery`
    and `ProcNetTcpSocketStats` already use.
    """

    def __init__(
        self,
        process_spawner: ProcessSpawner,
        nmcli_path: str,
        connection_name: str,
        nm_state_root: Path,
        timeout_s: float,
    ) -> None:
        self._process_spawner = process_spawner
        self._nmcli_path = nmcli_path
        self._connection_name = connection_name
        self._nm_state_root = nm_state_root
        self._timeout_s = timeout_s

    async def is_available(self) -> bool:
        """Return whether `nmcli` runs and reports a running NetworkManager.

        Never raises: this is the question every degraded path asks first.
        """
        try:
            stdout = await self._run(["--terse", "-f", "RUNNING", "general"])
        except (WiredShareUnavailableError, WiredShareCommandError):
            return False
        return "running" in stdout.strip().lower()

    async def list_wired_interfaces(self) -> tuple[WiredInterface, ...]:
        """Enumerate every Ethernet device, with enough state to avoid killing the uplink."""
        try:
            status_stdout = await self._run(
                [
                    "--terse",
                    "--colors",
                    "no",
                    "-f",
                    "DEVICE,TYPE,STATE,CONNECTION",
                    "device",
                    "status",
                ]
            )
        except (WiredShareUnavailableError, WiredShareCommandError):
            return ()

        interfaces: list[WiredInterface] = []
        for device, device_type, state, connection in parse_device_status(status_stdout):
            if device_type != _ETHERNET_DEVICE_TYPE:
                continue
            interfaces.append(await self._describe_interface(device, state, connection))
        return tuple(interfaces)

    async def _describe_interface(self, device: str, state: str, connection: str) -> WiredInterface:
        """Build one `WiredInterface`, degrading to the status-row data on failure.

        A device that cannot be described in detail still appears in the list
        with what the status row already told us — a port silently missing from
        the picker is worse than one described sparsely.
        """
        active_connection = connection or None
        try:
            detail_stdout = await self._run(
                [
                    "--terse",
                    "--colors",
                    "no",
                    "-f",
                    "GENERAL.STATE,GENERAL.HWADDR,GENERAL.CONNECTION,"
                    "IP4.ADDRESS,IP4.GATEWAY,WIRED-PROPERTIES.CARRIER,GENERAL.TYPE",
                    "device",
                    "show",
                    device,
                ]
            )
        except (WiredShareUnavailableError, WiredShareCommandError):
            return WiredInterface(
                name=device,
                mac_address=None,
                state=state,
                active_connection_name=active_connection,
                ipv4_addresses=(),
                carries_default_route=False,
                carrier_up=None,
            )

        properties = parse_property_rows(detail_stdout)
        # nmcli prints "on"/"off" here rather than "yes"/"no", so neither
        # `parse_yes_no` alone nor a bare truthiness check is enough — an
        # unplugged port would read as plugged in on the second. Absent means
        # this nmcli did not report the carrier, which is "unknown", not "down".
        carrier_text = properties.get("WIRED-PROPERTIES.CARRIER")
        carrier_up: bool | None = None
        if carrier_text is not None:
            carrier_up = carrier_text.strip().lower() == "on" or parse_yes_no(carrier_text)

        return WiredInterface(
            name=device,
            mac_address=properties.get("GENERAL.HWADDR") or None,
            state=properties.get("GENERAL.STATE", state),
            active_connection_name=active_connection,
            ipv4_addresses=collect_indexed_property(properties, "IP4.ADDRESS"),
            carries_default_route=bool(properties.get("IP4.GATEWAY", "").strip()),
            carrier_up=carrier_up,
        )

    async def read_state(self) -> WiredShareRuntimeState:
        """Read Sentry's wired profile back from NetworkManager."""
        try:
            stdout = await self._run(
                [
                    "--terse",
                    "--colors",
                    "no",
                    "-f",
                    "connection.id,connection.interface-name,connection.autoconnect,"
                    "ipv4.method,ipv4.addresses,GENERAL.STATE",
                    "connection",
                    "show",
                    self._connection_name,
                ]
            )
        except WiredShareCommandError:
            # nmcli exits non-zero when the profile simply does not exist, which
            # is the ordinary "not configured yet" state rather than a failure.
            return _absent_state()

        properties = parse_property_rows(stdout)
        if not properties:
            return _absent_state()

        activation_state = properties.get("GENERAL.STATE", "").strip() or None
        gateway_cidr = collect_indexed_property(properties, "ipv4.addresses")

        return WiredShareRuntimeState(
            profile_exists=True,
            active=bool(activation_state and "activated" in activation_state.lower()),
            autoconnect=parse_yes_no(properties.get("connection.autoconnect", "")),
            interface=properties.get("connection.interface-name") or None,
            gateway_cidr=gateway_cidr[0] if gateway_cidr else None,
            activation_state=activation_state,
        )

    async def apply_profile(self, profile: WiredShareProfile) -> None:
        """Create the profile if absent, then set every property to match `profile`."""
        state = await self.read_state()
        if not state.profile_exists:
            await self._run(
                [
                    "connection",
                    "add",
                    "type",
                    "ethernet",
                    "ifname",
                    profile.interface,
                    "con-name",
                    self._connection_name,
                    "autoconnect",
                    "no",
                ]
            )
        await self._run(self.modify_argv(profile))

    def modify_argv(self, profile: WiredShareProfile) -> list[str]:
        """Build the `connection modify` argv for `profile`.

        Public and split out for the same reason the hotspot's equivalent is:
        the exact property set is the part worth inspecting on its own, without
        a subprocess anywhere near the assertion.
        """
        return [
            "connection",
            "modify",
            self._connection_name,
            "connection.interface-name",
            profile.interface,
            "connection.autoconnect",
            yes_no(profile.autoconnect),
            # `shared` is the whole feature: NetworkManager assigns the address
            # below to this port, starts a dnsmasq serving DHCP and DNS on it,
            # and sets up NAT to whatever uplink the host still has. A plugged-in
            # laptop gets an address without anything else on the network.
            "ipv4.method",
            "shared",
            "ipv4.addresses",
            profile.gateway_cidr,
            # Wired sharing must never become the host's default route. Without
            # this, NetworkManager can prefer the shared connection's own
            # (nonexistent) gateway over the real uplink on a Pi that still has
            # one, which takes the Pi off the internet to serve a single cable.
            "ipv4.never-default",
            "yes",
            # No IPv6 counterpart is configured, so it is switched off rather
            # than left to negotiate a link-local address that nothing here
            # advertises and no client is told to use.
            "ipv6.method",
            "ignore",
        ]

    async def activate(self) -> None:
        """Bring Sentry's wired profile up."""
        await self._run(["connection", "up", self._connection_name])

    async def deactivate(self) -> None:
        """Bring the profile down, leaving it configured. Idempotent.

        `nmcli connection down` treats an already-down profile as an error, but
        this method's postcondition — the profile is not active — is already
        satisfied in that case, so reporting failure is wrong. The already-down
        case is confirmed by re-reading state rather than by matching nmcli's
        message: the wording is not API, and a real failure to tear down an
        active share must still surface, since that one leaves the Pi's uplink
        port serving DHCP.
        """
        try:
            await self._run(["connection", "down", self._connection_name])
        except WiredShareCommandError:
            if (await self.read_state()).active:
                raise

    async def set_autoconnect(self, autoconnect: bool) -> None:
        """Set whether the profile comes up on boot."""
        await self._run(
            [
                "connection",
                "modify",
                self._connection_name,
                "connection.autoconnect",
                yes_no(autoconnect),
            ]
        )

    async def delete_profile(self) -> None:
        """Delete the profile entirely."""
        await self._run(["connection", "delete", self._connection_name])

    async def active_connection_on(self, interface: str) -> str | None:
        """Return the profile currently active on `interface`, or None."""
        try:
            stdout = await self._run(
                ["--terse", "--colors", "no", "-f", "NAME,DEVICE", "connection", "show", "--active"]
            )
        except (WiredShareUnavailableError, WiredShareCommandError):
            return None
        for name, device in parse_active_connections(stdout):
            if device == interface and name != self._connection_name:
                return name
        return None

    async def activate_named(self, connection_name: str) -> None:
        """Bring an arbitrary previously-recorded profile back up (the rollback target)."""
        await self._run(["connection", "up", connection_name])

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        """Return the share's DHCP leases, or None when no lease file can be read."""
        return read_dnsmasq_leases(self._nm_state_root, interface)

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        """Ask the share's dnsmasq to forget one lease, via `dhcp_release`.

        Not a lease-file edit: that file is mounted read-only, and it is
        dnsmasq's own state rather than a database — dnsmasq holds leases in
        memory and rewrites the file, so a deleted line reappears at the next
        write. `dhcp_release` sends a DHCPRELEASE the server acts on.

        Runs `dhcp_release` rather than `nmcli`, so it does not go through
        `_run`: that helper prefixes `self._nmcli_path`, which does not apply.
        The container shares the host's network namespace (`network_mode: host`),
        which is what lets a release sent here reach the dnsmasq bound to the
        shared interface.
        """
        argv = [_DHCP_RELEASE_PATH, interface, ip_address, mac_address]
        _logger.debug("running dhcp_release: %s", " ".join(argv))
        try:
            process = await self._process_spawner.spawn(
                argv,
                {"PATH": os.environ.get("PATH", _FALLBACK_SPAWN_PATH), "LC_ALL": "C"},
                name="dhcp_release",
                capture_output=True,
            )
        except OSError as error:
            raise WiredShareUnavailableError(
                f"dhcp_release could not be started: {error}"
            ) from error

        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=self._timeout_s)
        except TimeoutError as error:
            process.kill()
            raise WiredShareTimeoutError(
                f"dhcp_release did not finish within {self._timeout_s:.0f}s",
                stderr_tail=None,
                exit_code=None,
            ) from error

        _, stderr = await process.communicate()
        if exit_code != 0:
            stderr_tail = stderr.decode("utf-8", errors="replace")[-STDERR_TRUNCATE_CHARS:]
            raise WiredShareCommandError(
                f"dhcp_release exited {exit_code}",
                stderr_tail=stderr_tail or None,
                exit_code=exit_code,
            )

    async def _run(self, arguments: Sequence[str]) -> str:
        """Run one `nmcli` invocation and return its stdout.

        Takes no `secret` parameter, unlike the hotspot adapter's equivalent:
        no wired-sharing command carries one, so the argv is safe to log
        verbatim and stderr is safe to surface without redaction.
        """
        argv = [self._nmcli_path, *arguments]
        # LC_ALL=C is load-bearing, not tidiness: nmcli localises its field
        # labels, and every parser this module uses matches them by name.
        spawn_env = {
            "PATH": os.environ.get("PATH", _FALLBACK_SPAWN_PATH),
            "LC_ALL": "C",
        }
        _logger.debug("running nmcli: %s", " ".join(argv))

        try:
            process = await self._process_spawner.spawn(
                argv, spawn_env, name="nmcli", capture_output=True
            )
        except OSError as error:
            raise WiredShareUnavailableError(f"nmcli could not be started: {error}") from error

        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=self._timeout_s)
        except TimeoutError as error:
            process.kill()
            raise WiredShareTimeoutError(
                f"nmcli did not finish within {self._timeout_s:.0f}s",
                stderr_tail=None,
                exit_code=None,
            ) from error

        stdout, stderr = await process.communicate()
        if exit_code != 0:
            stderr_tail = stderr.decode("utf-8", errors="replace")[-STDERR_TRUNCATE_CHARS:]
            raise WiredShareCommandError(
                f"nmcli exited {exit_code}",
                stderr_tail=stderr_tail or None,
                exit_code=exit_code,
            )
        return stdout.decode("utf-8", errors="replace")


def _absent_state() -> WiredShareRuntimeState:
    """The state of a host where Sentry's wired profile does not exist."""
    return WiredShareRuntimeState(
        profile_exists=False,
        active=False,
        autoconnect=False,
        interface=None,
        gateway_cidr=None,
        activation_state=None,
    )


class UnavailableWiredShareController:
    """A `WiredShareController` for hosts with no `nmcli` or no NetworkManager.

    The null-object counterpart to `UnavailableWifiApController`, and it makes
    the same deliberate exception for lease reading: that needs no
    NetworkManager at all — it is a plain file read — so `nm_state_root` is
    still honoured here rather than claiming an empty network on a host whose
    lease file is sitting right there on disk.
    """

    def __init__(self, reason: str, nm_state_root: Path | None = None) -> None:
        self._reason = reason
        self._nm_state_root = nm_state_root

    async def is_available(self) -> bool:
        """Always False — that is the entire point of this object."""
        return False

    async def list_wired_interfaces(self) -> tuple[WiredInterface, ...]:
        """No interfaces are enumerable without NetworkManager."""
        return ()

    async def read_state(self) -> WiredShareRuntimeState:
        """Report the profile as absent."""
        return _absent_state()

    async def apply_profile(self, profile: WiredShareProfile) -> None:
        """Refuse: there is nothing here to configure."""
        raise WiredShareUnavailableError(self._reason)

    async def activate(self) -> None:
        """Refuse: there is nothing here to activate."""
        raise WiredShareUnavailableError(self._reason)

    async def deactivate(self) -> None:
        """Refuse: there is nothing here to deactivate."""
        raise WiredShareUnavailableError(self._reason)

    async def set_autoconnect(self, autoconnect: bool) -> None:
        """Refuse: there is no profile to configure."""
        raise WiredShareUnavailableError(self._reason)

    async def delete_profile(self) -> None:
        """Refuse: there is no profile to delete."""
        raise WiredShareUnavailableError(self._reason)

    async def active_connection_on(self, interface: str) -> str | None:
        """Nothing is knowable about the host's connections here."""
        return None

    async def activate_named(self, connection_name: str) -> None:
        """Refuse: there is nothing here to activate."""
        raise WiredShareUnavailableError(self._reason)

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        """Refuse: there is no shared connection here whose leases could be released."""
        raise WiredShareUnavailableError(self._reason)

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        """Read the leases anyway when a state root is known; None means unknown, not zero."""
        if self._nm_state_root is None:
            return None
        return read_dnsmasq_leases(self._nm_state_root, interface)
