"""Pure parsers for `nmcli --terse` output, shared by every nmcli-backed adapter.

Extracted from `nmcli_wifi_ap.py` when a second controller — the wired-sharing
one (ADR-0014) — needed exactly the same escaping and property-row handling.
Everything here is a module-level pure function with no I/O anywhere near it,
which is the whole point: nmcli's terse escaping is the genuinely bug-prone part
of driving NetworkManager, and it is exercised against fixture text with no
subprocess involved.

Nothing in this module knows what a hotspot or a wired share *is*. It converts
bytes nmcli printed into Python values, and stops there.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.backend.interfaces.types import HotspotClient

STDERR_TRUNCATE_CHARS = 400
"""How much of a failed command's stderr reaches an operator. Bounded because it
lands in an HTTP body and a log line, and neither should carry an unbounded
attacker- or driver-controlled string."""

REDACTED_PLACEHOLDER = "***"


def split_terse_row(row: str) -> tuple[str, ...]:
    """Split one `nmcli --terse` output row into its fields.

    nmcli separates fields with `:` and escapes any literal `:` or `\\` inside a
    value as `\\:` and `\\\\`. A naive `row.split(":")` therefore corrupts every
    row containing an SSID with a colon in it — a legal and not-especially-rare
    network name — silently shifting every subsequent field by one. This is the
    single most bug-prone piece of the whole adapter layer, which is why it is a
    pure function with no I/O anywhere near it.
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


def read_dnsmasq_leases(
    nm_state_root: Path, interface: str | None = None
) -> tuple[HotspotClient, ...] | None:
    """Read dnsmasq lease files under `nm_state_root`, or `None` if there are none.

    Deliberately standalone, and deliberately shared by *every* controller:
    reading a lease file is an ordinary filesystem read with no D-Bus, no
    `nmcli` and no NetworkManager involved. A host that cannot *control* a
    shared connection can still perfectly well report the leases of one, and
    throwing that away just because the control path is unavailable would report
    "no clients" where the honest answer is on disk.

    Globs rather than composing an exact filename: the interface in the filename
    is whatever NetworkManager used, and a wrong guess would silently report an
    empty network instead of an unreadable one. `None` means unknown and must
    never be rendered as zero.

    `interface` narrows the glob to one interface's lease file, which is what
    keeps the WiFi hotspot's clients and the wired share's clients apart when
    both are running at once. Passing `None` keeps the original behaviour of
    merging every lease file on the host, which is what a caller wants when it
    does not know (or does not care) which interface served them.
    """
    pattern = "dnsmasq-*.leases" if interface is None else f"dnsmasq-{interface}.leases"
    try:
        lease_paths = sorted(nm_state_root.glob(pattern))
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


def redact_text(text: str, secret: str | None) -> str:
    """Return `text` with `secret` scrubbed out of it.

    nmcli can echo a property value back inside a parse error, so a failed
    command's stderr is not safe to surface verbatim. Applied before any stderr
    reaches an error body, an SSE notice, or a log record.
    """
    if not secret:
        return text
    return text.replace(secret, REDACTED_PLACEHOLDER)


def yes_no(value: bool) -> str:
    """Render a boolean the way nmcli expects it on the command line."""
    return "yes" if value else "no"


def parse_yes_no(value: str) -> bool:
    """Parse nmcli's boolean rendering, treating anything unrecognised as False."""
    return value.strip().lower() in {"yes", "true", "1"}
