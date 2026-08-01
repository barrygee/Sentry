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

    def resume(self) -> None:
        """Send `SIGCONT` (or process-group equivalent), a no-op on an already-running process.

        A process stopped by `SIGSTOP` (e.g. `pkill -STOP`, or a genuinely
        wedged driver left in stopped state) never handles `SIGTERM` — the
        signal stays pending until the process is continued, which never
        happens on its own. Callers send this before `terminate()` so a
        stopped-but-otherwise-healthy process gets a chance to actually
        receive and act on the polite signal that follows; they must never
        rely on this alone, since a genuinely hung process may ignore
        `SIGTERM` even once continued, and only `kill()` is guaranteed to
        remove it.
        """
        ...

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return `(stdout, stderr)` captured so far, once the process has exited.

        Only meaningful when the process was spawned with `capture_output=True`
        (`ProcessSpawner.spawn`) — otherwise both are always empty. Must be
        awaited only after `wait()` has completed (or concurrently with it);
        used by `EepromService` to surface `rtl_eeprom`'s stderr in the `notice`
        it publishes on failure, never by the long-lived `rtl_tcp`/relay pairs
        `SupervisorService` supervises (which are never captured, so an
        unread pipe can never fill and deadlock a process meant to run for
        hours).
        """
        ...


@runtime_checkable
class ProcessSpawner(Protocol):
    """Starts new OS processes on behalf of a service."""

    async def spawn(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        name: str,
        capture_output: bool = False,
    ) -> ManagedProcess:
        """Start `argv` with the given environment and return its handle.

        `argv` is always a fully-formed list — implementations must never
        build or accept a shell string (architecture §7.6, §12.7, §12.10).
        `name` is a human-readable label for logging only. `capture_output`
        pipes stdout/stderr so `ManagedProcess.communicate()` can return them
        after exit — only ever set for short-lived, one-shot commands
        (`rtl_eeprom`), never for a supervised long-running pair, to avoid
        an unread pipe filling and stalling a process meant to run for hours.
        """
        ...
