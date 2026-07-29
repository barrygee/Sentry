"""Network-introspection adapters: bind probing and `/proc/net/tcp` client counts.

Both are best-effort, nullable-throughout: `SocketPortProber` performs a real
bind/close probe, while `ProcNetTcpSocketStats` parses `/proc/net/tcp{,6}` and
returns `None` wherever that file does not exist (any non-Linux platform,
including macOS dev machines), matching `SocketStatsSource`'s "None means
unknown, never zero" contract (architecture §4.2).
"""

from __future__ import annotations

import socket
from pathlib import Path

# /proc/net/tcp's fixed column layout (whitespace-separated, after the header
# line): "sl local_address rem_address st tx_queue:rx_queue tr:tm->when
# retrnsmt uid timeout inode ...". Only local_address (port) and st
# (connection state) are needed here.
_LOCAL_ADDRESS_COLUMN = 1
_STATE_COLUMN = 3
_TCP_STATE_ESTABLISHED = "01"


class SocketPortProber:
    """Real `PortProber` performing an actual bind-and-close probe."""

    def is_bindable(self, host: str, port: int) -> bool:
        """Return whether `(host, port)` can be bound right now.

        Uses `SO_REUSEADDR` so a socket of this process's own in `TIME_WAIT`
        does not produce a false negative, matching the OS's own notion of
        "available" as closely as a single-process probe can.
        """
        for family in (socket.AF_INET, socket.AF_INET6):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as probe_socket:
                    probe_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe_socket.bind((host, port))
            except OSError:
                return False
        return True


def _parse_local_port(local_address_field: str) -> int | None:
    """Parse the `<hex_addr>:<hex_port>` field `/proc/net/tcp` reports, or `None`.

    A pure helper so the hex-port parsing itself is unit-testable against a
    fixture file without a real `/proc` filesystem.
    """
    _address, _, port_hex = local_address_field.partition(":")
    if not port_hex:
        return None
    try:
        return int(port_hex, 16)
    except ValueError:
        return None


def count_established_connections(proc_net_tcp_contents: str, port: int) -> int:
    """Count `ESTABLISHED` rows for `port` in one `/proc/net/tcp`-formatted file's contents.

    A pure helper extracted from `ProcNetTcpSocketStats` so the parser is
    tested against a fixture file's contents directly (architecture §12.15).
    Malformed rows (too few columns, an unparseable port or state) are
    skipped rather than raising — one corrupt line must not hide every other
    connection's count.
    """
    established_count = 0
    lines = proc_net_tcp_contents.splitlines()
    for line in lines[1:]:  # line 0 is the column-header row
        columns = line.split()
        if len(columns) <= max(_LOCAL_ADDRESS_COLUMN, _STATE_COLUMN):
            continue
        local_port = _parse_local_port(columns[_LOCAL_ADDRESS_COLUMN])
        if local_port != port:
            continue
        if columns[_STATE_COLUMN] == _TCP_STATE_ESTABLISHED:
            established_count += 1
    return established_count


class ProcNetTcpSocketStats:
    """Real `SocketStatsSource` parsing `/proc/net/tcp` and `/proc/net/tcp6`.

    `proc_root` is injected (production passes `Path("/proc")`, tests pass a
    fixture directory containing a `net/tcp` file) so the parser is exercised
    identically in both contexts, the same root-parameterisation discipline
    as `SysfsUsbDiscovery`.
    """

    def __init__(self, proc_root: Path) -> None:
        self._tcp_paths = [proc_root / "net" / "tcp", proc_root / "net" / "tcp6"]

    def established_peers(self, port: int) -> int | None:
        """Return the established-connection count for `port`, or `None` if unsupported.

        `None` is returned only when *neither* `/proc/net/tcp` nor
        `/proc/net/tcp6` can be read at all (the platform has no `/proc`) —
        if one of the two is readable, its count is used and the missing one
        contributes zero, since a dual-stack listener may only have IPv4 or
        only IPv6 peers connected.
        """
        total = 0
        any_readable = False
        for tcp_path in self._tcp_paths:
            try:
                contents = tcp_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            any_readable = True
            total += count_established_connections(contents, port)
        return total if any_readable else None
