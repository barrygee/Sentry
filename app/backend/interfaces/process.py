"""Process-spawning seam used by `services.supervisor` and `services.eeprom`.

Nothing outside `adapters/` may call `asyncio.create_subprocess_exec` or any
other subprocess primitive directly — everything goes through `ProcessSpawner`
so the supervisor's crash/backoff/wedge logic is fully exercisable against a
fake with no real processes (architecture §4.1, §12.7).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class ManagedProcess(Protocol):
    """A single spawned OS process under supervision.

    Wraps a real `rtl_tcp`, relay, or `rtl_eeprom` invocation (or a fake
    standing in for one in tests).
    """

    @property
    def pid(self) -> int:
        """The OS process ID."""
        ...

    @property
    def returncode(self) -> int | None:
        """The process's exit code, or None while it is still running."""
        ...

    async def wait(self) -> int:
        """Block until the process exits and return its exit code."""
        ...

    def terminate(self) -> None:
        """Send a graceful stop signal (SIGTERM or process-group equivalent)."""
        ...

    def kill(self) -> None:
        """Send a forceful stop signal (SIGKILL), for use after a grace period."""
        ...


@runtime_checkable
class ProcessSpawner(Protocol):
    """Starts new OS processes on behalf of a service."""

    async def spawn(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        name: str,
    ) -> ManagedProcess:
        """Start `argv` with the given environment and return its handle.

        `argv` is always a fully-formed list — implementations must never
        build or accept a shell string (architecture §7.6, §12.7, §12.10).
        `name` is a human-readable label for logging only.
        """
        ...
