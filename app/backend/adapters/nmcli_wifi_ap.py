"""Real `WifiApController` driving the host's NetworkManager through `nmcli` (ADR-0007).

`nmcli` is a D-Bus client, so this only works where the host's system bus socket
has been mounted into the container. On any other host — a developer laptop, a
Pi running `dhcpcd` — construction succeeds but `is_available()` answers False
and every mutator raises `WifiApUnavailableError`, which is what lets
`GET /api/hotspot` stay a 200 rather than failing.

Two disciplines run through this module.

**Every command is a fully-formed list argv through `ProcessSpawner`**, never a
shell string, matching the one-shot pattern `services/eeprom.py` already uses
for `rtl_eeprom`. There is no shell, so no metacharacter in an SSID or
passphrase can mean anything — injection is structurally impossible rather than
filtered out.

**All parsing lives in pure module-level functions**, the discipline
`adapters/net.py` follows, so the genuinely bug-prone part (nmcli's terse
escaping) is exercised against fixture text with no subprocess involved.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.types import (
    HotspotClient,
    HotspotProfile,
    HotspotRuntimeState,
    HotspotSecurity,
    WirelessInterface,
)
from app.backend.interfaces.wifi_ap import (
    WifiApCommandError,
    WifiApTimeoutError,
    WifiApUnavailableError,
)

_logger = logging.getLogger(__name__)

_FALLBACK_SPAWN_PATH = "/usr/local/bin:/usr/bin:/bin"

STDERR_TRUNCATE_CHARS = 400
"""How much of a failed command's stderr reaches an operator. Bounded because it
lands in an HTTP body and a log line, and neither should carry an unbounded
attacker- or driver-controlled string."""

REDACTED_PLACEHOLDER = "***"

_PSK_PROPERTY = "802-11-wireless-security.psk"

_DHCP_RELEASE_PATH = "/usr/bin/dhcp_release"
"""From `dnsmasq-utils`, installed in the runtime image. An absolute path for
the same reason `nmcli`'s is: a bare name would be resolved against `PATH`."""

_KEY_MANAGEMENT_BY_SECURITY: Mapping[HotspotSecurity, str] = {"wpa2": "wpa-psk", "wpa3": "sae"}
_SECURITY_BY_KEY_MANAGEMENT: Mapping[str, HotspotSecurity] = {"wpa-psk": "wpa2", "sae": "wpa3"}


def split_terse_row(row: str) -> tuple[str, ...]:
    """Split one `nmcli --terse` output row into its fields.

    nmcli separates fields with `:` and escapes any literal `:` or `\\` inside a
    value as `\\:` and `\\\\`. A naive `row.split(":")` therefore corrupts every
    row containing an SSID with a colon in it — a legal and not-especially-rare
    network name — silently shifting every subsequent field by one. This is the
    single most bug-prone piece of the whole adapter, which is why it is a pure
    function with no I/O anywhere near it.
    """
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in row:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        # A trailing lone backslash is malformed; keep it literally rather than
        # dropping a character the operator may need to see in a diagnostic.
        current.append("\\")
    fields.append("".join(current))
    return tuple(fields)


def parse_device_status(stdout: str) -> tuple[tuple[str, str, str, str], ...]:
    """Parse `nmcli -f DEVICE,TYPE,STATE,CONNECTION device status` into rows.

    Returns `(device, type, state, connection)` tuples. Rows with too few
    fields are skipped rather than raising — one unexpected line must not hide
    every other interface.
    """
    rows: list[tuple[str, str, str, str]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        fields = split_terse_row(line)
        if len(fields) < 4:
            continue
        rows.append((fields[0], fields[1], fields[2], fields[3]))
    return tuple(rows)


def parse_property_rows(stdout: str) -> dict[str, str]:
    """Parse `nmcli -f <props> device show`/`connection show` into a property map.

    Both commands emit `PROPERTY:value` rows. Repeated properties (nmcli emits
    `IP4.ADDRESS[1]`, `IP4.ADDRESS[2]`, ...) keep their bracketed suffix, so the
    caller can collect them without them overwriting each other.
    """
    properties: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        fields = split_terse_row(line)
        if len(fields) < 2:
            continue
        properties[fields[0]] = ":".join(fields[1:])
    return properties


def collect_indexed_property(properties: Mapping[str, str], prefix: str) -> tuple[str, ...]:
    """Collect every `PREFIX[n]` value from a parsed property map, in index order.

    nmcli reports multi-valued properties as `IP4.ADDRESS[1]`, `IP4.ADDRESS[2]`
    and so on; older versions emit a bare `IP4.ADDRESS`. Both are handled.
    """
    matches: list[tuple[int, str]] = []
    for key, value in properties.items():
        if key == prefix:
            matches.append((0, value))
        elif key.startswith(f"{prefix}[") and key.endswith("]"):
            index_text = key[len(prefix) + 1 : -1]
            try:
                matches.append((int(index_text), value))
            except ValueError:
                continue
    return tuple(value for _index, value in sorted(matches) if value)


def parse_active_connections(stdout: str) -> tuple[tuple[str, str], ...]:
    """Parse `nmcli -f NAME,DEVICE connection show --active` into `(name, device)` pairs."""
    pairs: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        fields = split_terse_row(line)
        if len(fields) < 2:
            continue
        pairs.append((fields[0], fields[1]))
    return tuple(pairs)


def parse_dnsmasq_leases(contents: str) -> tuple[HotspotClient, ...]:
    """Parse one dnsmasq `.leases` file's contents into client records.

    The format is one lease per line: `<expiry_epoch_s> <mac> <ipv4> <hostname>
    <client-id>`, with `*` standing in for an absent hostname or client id.

    Pure, so it is exercised against a fixture file with no `/var` anywhere.
    Rows that are too short or carry an unparseable expiry are skipped rather
    than raising — one corrupt line must not hide every other client, the same
    rule `count_established_connections` follows in `adapters/net.py`.

    Every lease is returned, expired ones included, carrying its expiry so the
    API layer can *mark* rather than hide them. A lease is not an association,
    and silently dropping the lapsed ones would imply a precision this source
    does not have.
    """
    clients: list[HotspotClient] = []
    for line in contents.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        expiry_text, mac_address, ip_address, hostname = fields[0], fields[1], fields[2], fields[3]
        try:
            expiry_epoch_seconds = int(expiry_text)
        except ValueError:
            continue
        if not mac_address or not ip_address:
            continue
        clients.append(
            HotspotClient(
                mac_address=mac_address.lower(),
                ip_address=ip_address,
                hostname=None if hostname == "*" else hostname,
                lease_expires_at_ms=expiry_epoch_seconds * 1000,
            )
        )
    return tuple(clients)


def read_dnsmasq_leases(nm_state_root: Path) -> tuple[HotspotClient, ...] | None:
    """Read every dnsmasq lease file under `nm_state_root`, or `None` if there are none.

    Deliberately standalone, and deliberately shared by *both* controllers:
    reading a lease file is an ordinary filesystem read with no D-Bus, no
    `nmcli` and no NetworkManager involved. A host that cannot *control* a
    hotspot can still perfectly well report the leases of one, and throwing
    that away just because the control path is unavailable would report "no
    clients" where the honest answer is on disk.

    Globs rather than composing an exact filename: the interface in the
    filename is whatever NetworkManager used, and a wrong guess would silently
    report an empty network instead of an unreadable one. `None` means unknown
    and must never be rendered as zero.
    """
    try:
        lease_paths = sorted(nm_state_root.glob("dnsmasq-*.leases"))
    except OSError:
        return None
    if not lease_paths:
        return None

    clients: list[HotspotClient] = []
    any_readable = False
    for lease_path in lease_paths:
        try:
            contents = lease_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        any_readable = True
        clients.extend(parse_dnsmasq_leases(contents))
    return tuple(clients) if any_readable else None


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Return `argv` with any passphrase value replaced by a placeholder.

    The element *following* the psk property name is the secret. Used for every
    log record this module emits; the raw argv is never logged, at any level.
    """
    redacted = list(argv)
    for index, element in enumerate(redacted):
        if element == _PSK_PROPERTY and index + 1 < len(redacted):
            redacted[index + 1] = REDACTED_PLACEHOLDER
    return tuple(redacted)


def redact_text(text: str, secret: str | None) -> str:
    """Return `text` with `secret` scrubbed out of it.

    nmcli can echo a property value back inside a parse error, so a failed
    command's stderr is not safe to surface verbatim. Applied before any stderr
    reaches an error body, an SSE notice, or a log record.
    """
    if not secret:
        return text
    return text.replace(secret, REDACTED_PLACEHOLDER)


def _yes_no(value: bool) -> str:
    """Render a boolean the way nmcli expects it on the command line."""
    return "yes" if value else "no"


def _parse_yes_no(value: str) -> bool:
    """Parse nmcli's boolean rendering, treating anything unrecognised as False."""
    return value.strip().lower() in {"yes", "true", "1"}


class NmcliWifiApController:
    """Drives one NetworkManager connection profile through the `nmcli` binary.

    `nm_state_root` is injected rather than hard-coded — production passes
    `/var/lib/NetworkManager`, tests point it at a fixture directory — the same
    root-parameterisation discipline `SysfsUsbDiscovery` and
    `ProcNetTcpSocketStats` already use.
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
        except (WifiApUnavailableError, WifiApCommandError):
            return False
        return "running" in stdout.strip().lower()

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        """Enumerate every wifi device, with enough state to avoid killing the uplink."""
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
        except (WifiApUnavailableError, WifiApCommandError):
            return ()

        interfaces: list[WirelessInterface] = []
        for device, device_type, state, connection in parse_device_status(status_stdout):
            if device_type != "wifi":
                continue
            interfaces.append(await self._describe_interface(device, state, connection))
        return tuple(interfaces)

    async def _describe_interface(
        self, device: str, state: str, connection: str
    ) -> WirelessInterface:
        """Build one `WirelessInterface`, degrading to the status-row data on failure.

        A device that cannot be described in detail still appears in the list
        with what the status row already told us — an interface silently missing
        from the picker is worse than one described sparsely.
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
                    "IP4.ADDRESS,IP4.GATEWAY,WIFI-PROPERTIES.AP,GENERAL.TYPE",
                    "device",
                    "show",
                    device,
                ]
            )
        except (WifiApUnavailableError, WifiApCommandError):
            return WirelessInterface(
                name=device,
                mac_address=None,
                supports_ap=None,
                state=state,
                active_connection_name=active_connection,
                station_ssid=None,
                ipv4_addresses=(),
                carries_default_route=False,
            )

        properties = parse_property_rows(detail_stdout)
        supports_ap_text = properties.get("WIFI-PROPERTIES.AP")
        return WirelessInterface(
            name=device,
            mac_address=properties.get("GENERAL.HWADDR") or None,
            # Absent means this nmcli did not report the capability, not that the
            # radio lacks it — the field is version-dependent, so None here means
            # "assume capable and let activation fail loudly" rather than refusing.
            supports_ap=None if supports_ap_text is None else _parse_yes_no(supports_ap_text),
            state=properties.get("GENERAL.STATE", state),
            active_connection_name=active_connection,
            # The profile name is the best available proxy for the joined SSID:
            # NetworkManager names a station profile after the network by default.
            #
            # Except when that profile is our own AP. NetworkManager reports the
            # hotspot's connection as the interface's active one while it is up,
            # which read back as the Pi having *joined* a network called
            # `sentry-hotspot` — the warning above the form said the Pi's own
            # link was "to sentry-hotspot", naming the hotspot it was serving.
            station_ssid=(
                active_connection
                if active_connection and active_connection != self._connection_name
                else None
            ),
            ipv4_addresses=collect_indexed_property(properties, "IP4.ADDRESS"),
            carries_default_route=bool(properties.get("IP4.GATEWAY", "").strip()),
        )

    async def read_state(self) -> HotspotRuntimeState:
        """Read Sentry's profile back from NetworkManager, secrets excluded."""
        try:
            stdout = await self._run(
                [
                    "--terse",
                    "--colors",
                    "no",
                    "-f",
                    "connection.id,connection.interface-name,connection.autoconnect,"
                    "802-11-wireless.ssid,802-11-wireless.hidden,802-11-wireless.mode,"
                    "802-11-wireless.band,802-11-wireless.channel,"
                    "802-11-wireless-security.key-mgmt,802-11-wireless-security.psk-flags,"
                    "ipv4.addresses,GENERAL.STATE",
                    "connection",
                    "show",
                    self._connection_name,
                ]
                # Deliberately no `-s`/`--show-secrets`. That absence is a security
                # control, not an oversight (ADR-0007): the stored passphrase must
                # never enter this process's memory, so `passphrase_set` below is
                # derived from key-mgmt being configured, never from the key itself.
            )
        except WifiApCommandError:
            # nmcli exits non-zero when the profile simply does not exist, which
            # is the ordinary "not configured yet" state rather than a failure.
            return _absent_state()

        properties = parse_property_rows(stdout)
        if not properties:
            return _absent_state()

        key_management = properties.get("802-11-wireless-security.key-mgmt", "").strip()
        band_text = properties.get("802-11-wireless.band", "").strip()
        channel_text = properties.get("802-11-wireless.channel", "").strip()
        activation_state = properties.get("GENERAL.STATE", "").strip() or None
        gateway_cidr = collect_indexed_property(properties, "ipv4.addresses")

        return HotspotRuntimeState(
            profile_exists=True,
            active=bool(activation_state and "activated" in activation_state.lower()),
            autoconnect=_parse_yes_no(properties.get("connection.autoconnect", "")),
            interface=properties.get("connection.interface-name") or None,
            ssid=properties.get("802-11-wireless.ssid") or None,
            hidden=_parse_yes_no(properties.get("802-11-wireless.hidden", "")),
            security=_SECURITY_BY_KEY_MANAGEMENT.get(key_management, "wpa2"),
            band="a" if band_text == "a" else "bg",
            channel=int(channel_text) if channel_text.isdigit() else 0,
            gateway_cidr=gateway_cidr[0] if gateway_cidr else None,
            passphrase_set=bool(key_management),
            activation_state=activation_state,
        )

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        """Create the profile if absent, then set every property to match `profile`."""
        state = await self.read_state()
        if not state.profile_exists:
            await self._run(
                [
                    "connection",
                    "add",
                    "type",
                    "wifi",
                    "ifname",
                    profile.interface,
                    "con-name",
                    self._connection_name,
                    "autoconnect",
                    "no",
                    "ssid",
                    profile.ssid,
                ],
                secret=passphrase,
            )
        await self._run(
            self._modify_argv(profile, passphrase),
            secret=passphrase,
        )

    def _modify_argv(self, profile: HotspotProfile, passphrase: str | None) -> list[str]:
        """Build the `connection modify` argv for `profile`.

        Split out so the exact property set — including the fact that the
        passphrase pair is *absent entirely* when unchanged, rather than written
        back as a placeholder — is inspectable on its own.
        """
        argv = [
            "connection",
            "modify",
            self._connection_name,
            "connection.interface-name",
            profile.interface,
            "connection.autoconnect",
            _yes_no(profile.autoconnect),
            "802-11-wireless.mode",
            "ap",
            "802-11-wireless.ssid",
            profile.ssid,
            "802-11-wireless.hidden",
            _yes_no(profile.hidden),
            "802-11-wireless.band",
            profile.band,
            # Channel 0 is Sentry's "automatic", but it is not a value nmcli
            # will take: it validates the text and refuses with "'0' is not a
            # valid channel", failing the whole `connection modify` — so with
            # Automatic selected (the default) no hotspot could ever be saved.
            # An empty string is nmcli's own way of resetting a property to
            # its default, which for this one *is* auto-select. Cleared rather
            # than omitted: omitting leaves whatever channel was there before,
            # so switching from Channel 6 back to Automatic would silently
            # keep pinning 6.
            "802-11-wireless.channel",
            "" if profile.channel == 0 else str(profile.channel),
            "802-11-wireless-security.key-mgmt",
            _KEY_MANAGEMENT_BY_SECURITY[profile.security],
            "802-11-wireless-security.proto",
            "rsn",
            "802-11-wireless-security.pairwise",
            "ccmp",
            "802-11-wireless-security.group",
            "ccmp",
            # 0 = the secret belongs to the system and lives in NetworkManager's
            # own root-only keyfile. Any other flag value makes NM ask a secret
            # agent for the key at activation time, and there is no agent in this
            # container, so the hotspot would simply never come up.
            "802-11-wireless-security.psk-flags",
            "0",
            "ipv4.method",
            "shared",
            "ipv4.addresses",
            profile.gateway_cidr,
            "ipv6.method",
            "ignore",
        ]
        if passphrase is not None:
            argv.extend([_PSK_PROPERTY, passphrase])
        return argv

    async def activate(self) -> None:
        """Bring Sentry's profile up."""
        await self._run(["connection", "up", self._connection_name])

    async def deactivate(self) -> None:
        """Bring Sentry's profile down, leaving it configured. Idempotent.

        `nmcli connection down` treats an already-down profile as an error
        ("'sentry-hotspot' is not an active connection"), but this method's
        postcondition — the profile is not active — is already satisfied in
        that case, so reporting failure is wrong. Saving settings with the
        hotspot switched off does exactly this, and the whole save reported a
        500 *after* having already written the profile, which is the worst of
        both: the change landed and the operator was told it had not.

        The already-down case is confirmed by re-reading state rather than by
        matching nmcli's message. The wording is not API, and a real failure to
        tear down an active hotspot must still surface — that one leaves a
        network on the air.
        """
        try:
            await self._run(["connection", "down", self._connection_name])
        except WifiApCommandError:
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
                _yes_no(autoconnect),
            ]
        )

    async def delete_profile(self) -> None:
        """Delete the profile, forgetting the SSID and the stored key."""
        await self._run(["connection", "delete", self._connection_name])

    async def active_connection_on(self, interface: str) -> str | None:
        """Return the profile currently active on `interface`, or None."""
        try:
            stdout = await self._run(
                ["--terse", "--colors", "no", "-f", "NAME,DEVICE", "connection", "show", "--active"]
            )
        except (WifiApUnavailableError, WifiApCommandError):
            return None
        for name, device in parse_active_connections(stdout):
            if device == interface and name != self._connection_name:
                return name
        return None

    async def activate_named(self, connection_name: str) -> None:
        """Bring an arbitrary previously-recorded profile back up (the rollback target)."""
        await self._run(["connection", "up", connection_name])

    def list_clients(self) -> tuple[HotspotClient, ...] | None:
        """Return the AP's DHCP leases, or None when no lease file can be read."""
        return read_dnsmasq_leases(self._nm_state_root)

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        """Ask the AP's dnsmasq to forget one lease, via `dhcp_release`.

        Not a lease-file edit: that file is mounted read-only, and it is
        dnsmasq's own state rather than a database — dnsmasq holds leases in
        memory and rewrites the file, so a deleted line reappears at the next
        write. `dhcp_release` sends a DHCPRELEASE the server acts on.

        Runs `dhcp_release` rather than `nmcli`, so it does not go through
        `_run`: that helper prefixes `self._nmcli_path` and redacts a
        passphrase, neither of which applies. The container shares the host's
        network namespace (`network_mode: host`), which is what lets a release
        sent here reach the dnsmasq bound to the AP interface.
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
            raise WifiApUnavailableError(f"dhcp_release could not be started: {error}") from error

        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=self._timeout_s)
        except TimeoutError as error:
            process.kill()
            raise WifiApTimeoutError(
                f"dhcp_release did not finish within {self._timeout_s:.0f}s",
                stderr_tail=None,
                exit_code=None,
            ) from error

        _, stderr = await process.communicate()
        if exit_code != 0:
            stderr_tail = stderr.decode("utf-8", errors="replace")[-STDERR_TRUNCATE_CHARS:]
            raise WifiApCommandError(
                f"dhcp_release exited {exit_code}",
                stderr_tail=stderr_tail or None,
                exit_code=exit_code,
            )

    async def _run(self, arguments: Sequence[str], secret: str | None = None) -> str:
        """Run one `nmcli` invocation and return its stdout.

        Follows the one-shot subprocess pattern `services/eeprom.py` established:
        list argv, minimal environment, captured output, a bounded wait, and a
        kill on timeout so a wedged NetworkManager cannot leave a process behind.
        """
        argv = [self._nmcli_path, *arguments]
        # LC_ALL=C is load-bearing, not tidiness: nmcli localises its field
        # labels, and every parser in this module matches them by name.
        spawn_env = {
            "PATH": os.environ.get("PATH", _FALLBACK_SPAWN_PATH),
            "LC_ALL": "C",
        }
        _logger.debug("running nmcli: %s", " ".join(redact_argv(argv)))

        try:
            process = await self._process_spawner.spawn(
                argv, spawn_env, name="nmcli", capture_output=True
            )
        except OSError as error:
            raise WifiApUnavailableError(f"nmcli could not be started: {error}") from error

        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=self._timeout_s)
        except TimeoutError as error:
            process.kill()
            raise WifiApTimeoutError(
                f"nmcli did not finish within {self._timeout_s:.0f}s",
                stderr_tail=None,
                exit_code=None,
            ) from error

        stdout, stderr = await process.communicate()
        if exit_code != 0:
            stderr_tail = redact_text(stderr.decode("utf-8", errors="replace"), secret)[
                -STDERR_TRUNCATE_CHARS:
            ]
            raise WifiApCommandError(
                f"nmcli exited {exit_code}",
                stderr_tail=stderr_tail or None,
                exit_code=exit_code,
            )
        return stdout.decode("utf-8", errors="replace")


def _absent_state() -> HotspotRuntimeState:
    """The state of a host where Sentry's profile does not exist."""
    return HotspotRuntimeState(
        profile_exists=False,
        active=False,
        autoconnect=False,
        interface=None,
        ssid=None,
        hidden=True,
        security="wpa2",
        band="bg",
        channel=0,
        gateway_cidr=None,
        passphrase_set=False,
        activation_state=None,
    )


class UnavailableWifiApController:
    """A `WifiApController` for hosts with no `nmcli` or no NetworkManager.

    The null-object counterpart to `main._NullRtlSdrLibrary`: constructing the
    real controller on a developer laptop would be pointless, and crashing
    startup over a missing optional capability would be worse. Reads degrade to
    empty/absent answers; every mutator raises `WifiApUnavailableError`, which
    the router maps to a 503.

    Lease reading is the one deliberate exception. It needs no NetworkManager
    at all — it is a plain file read — so `nm_state_root` is still honoured
    here rather than claiming an empty network on a host whose lease file is
    sitting right there on disk.
    """

    def __init__(self, reason: str, nm_state_root: Path | None = None) -> None:
        self._reason = reason
        self._nm_state_root = nm_state_root

    async def is_available(self) -> bool:
        """Always False — that is the entire point of this object."""
        return False

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        """No interfaces are enumerable without NetworkManager."""
        return ()

    async def read_state(self) -> HotspotRuntimeState:
        """Report the profile as absent."""
        return _absent_state()

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        """Refuse: there is nothing here to configure."""
        raise WifiApUnavailableError(self._reason)

    async def activate(self) -> None:
        """Refuse: there is nothing here to activate."""
        raise WifiApUnavailableError(self._reason)

    async def deactivate(self) -> None:
        """Refuse: there is nothing here to deactivate."""
        raise WifiApUnavailableError(self._reason)

    async def set_autoconnect(self, autoconnect: bool) -> None:
        """Refuse: there is no profile to configure."""
        raise WifiApUnavailableError(self._reason)

    async def delete_profile(self) -> None:
        """Refuse: there is no profile to delete."""
        raise WifiApUnavailableError(self._reason)

    async def active_connection_on(self, interface: str) -> str | None:
        """Nothing is knowable about the host's connections here."""
        return None

    async def activate_named(self, connection_name: str) -> None:
        """Refuse: there is nothing here to activate."""
        raise WifiApUnavailableError(self._reason)

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        """Refuse: there is no access point here whose leases could be released."""
        raise WifiApUnavailableError(self._reason)

    def list_clients(self) -> tuple[HotspotClient, ...] | None:
        """Read the leases anyway when a state root is known; None means unknown, not zero."""
        if self._nm_state_root is None:
            return None
        return read_dnsmasq_leases(self._nm_state_root)
