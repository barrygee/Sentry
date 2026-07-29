"""Network seams: pre-flight port availability and per-port client counts.

Both are advisory, best-effort views of the OS network stack, kept behind
Protocols so `port_allocator` and the status assembly can be tested without a
real socket or a real `/proc` filesystem.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PortProber(Protocol):
    """Pre-flight check for whether a TCP port can currently be bound."""

    def is_bindable(self, host: str, port: int) -> bool:
        """Return whether `(host, port)` can currently be bound.

        A probe, not a lock (architecture §8): the port can still be taken
        between this call and the actual spawn, which callers must treat as
        a `port_in_use` spawn failure rather than assume this result holds.
        """
        ...


@runtime_checkable
class SocketStatsSource(Protocol):
    """Counts established TCP peers connected to a given local port."""

    def established_peers(self, port: int) -> int | None:
        """Return the number of ESTABLISHED connections to `port`.

        Returns `None` on platforms where the underlying source (Linux's
        `/proc/net/tcp{,6}`) is unavailable — for example macOS development
        machines. Callers must treat `None` as "unknown", never as zero.
        """
        ...
