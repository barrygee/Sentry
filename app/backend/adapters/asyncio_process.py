"""Real `ProcessSpawner`/`ManagedProcess` over `asyncio.create_subprocess_exec`.

The only place in the production code that actually forks a process. Always
called with a fully-formed argv list — never a shell string (architecture
§4.2, §12.7, §12.9 pragma table).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Mapping, Sequence


class AsyncioManagedProcess:
    """A `ManagedProcess` wrapping a real `asyncio.subprocess.Process`.

    Started with `start_new_session=True` so the process (and any children it
    forks, e.g. `rtl_tcp`'s helper threads) can be killed as a single process
    group — a lone `SIGTERM`/`SIGKILL` to the child's PID would otherwise miss
    anything it spawned.
    """

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @property
    def pid(self) -> int:
        """The OS process ID of the spawned process's session leader."""
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        """The process's exit code, or None while it is still running."""
        return self._process.returncode

    async def wait(self) -> int:
        """Block until the process exits and return its exit code."""
        return await self._process.wait()

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return `(stdout, stderr)`, both empty if this process was not spawned with capture."""
        stdout, stderr = await self._process.communicate()
        return stdout or b"", stderr or b""

    def terminate(self) -> None:
        """Send `SIGTERM` to the whole process group started with this process."""
        self._signal_group(signal.SIGTERM)

    def kill(self) -> None:
        """Send `SIGKILL` to the whole process group started with this process."""
        self._signal_group(signal.SIGKILL)

    def resume(self) -> None:
        """Send `SIGCONT` to the whole process group started with this process."""
        self._signal_group(signal.SIGCONT)

    def _signal_group(self, sig: signal.Signals) -> None:
        """Deliver `sig` to the process group, falling back to the lone PID.

        The process may already have exited (a `ProcessLookupError`/
        `PermissionError` race between `wait()` completing and a caller still
        holding this handle) — that is not an error worth surfacing here,
        since the caller only wanted the process to be gone.
        """
        try:
            os.killpg(self._process.pid, sig)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                self._process.send_signal(sig)


class AsyncioProcessSpawner:
    """Real `ProcessSpawner` over `asyncio.create_subprocess_exec`.

    `spawn()` never interprets `argv` through a shell — the first element is
    the executable, matching `subprocess.Popen(shell=False)` semantics.
    """

    async def spawn(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        name: str,
        capture_output: bool = False,
    ) -> AsyncioManagedProcess:
        """Start `argv` as a new process group with exactly the given `env`.

        `name` is accepted for Protocol compatibility and used only in the
        (absent, by design) logging this thin adapter does not itself emit —
        callers that want spawn logging log around this call. `capture_output`
        pipes stdout/stderr for `communicate()`; left inherited (the default)
        for every long-running supervised process.
        """
        pipe = asyncio.subprocess.PIPE if capture_output else None
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=dict(env),
            start_new_session=True,
            stdout=pipe,
            stderr=pipe,
        )
        return AsyncioManagedProcess(process)
