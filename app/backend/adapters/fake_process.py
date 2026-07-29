"""Scriptable `ProcessSpawner`/`ManagedProcess` fakes for testing the supervisor.

Records every spawn call and hands back a `FakeManagedProcess` whose exit
timing and code the test drives directly — no real OS process is ever
started. This is what makes `services.supervisor`'s crash/backoff/wedge logic
exercisable deterministically (architecture §4.2, §12.7).
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecordedSpawn:
    """One call made to `FakeProcessSpawner.spawn()`, captured for assertions."""

    argv: tuple[str, ...]
    """The exact argv passed, as a tuple (immutable, safe to compare later)."""

    env: Mapping[str, str]
    """The exact environment mapping passed."""

    name: str
    """The human-readable label passed."""


class FakeManagedProcess:
    """A `ManagedProcess` double whose completion is driven by the test.

    `wait()` blocks until `complete(returncode)` is called, matching a real
    process's semantics: a test can spawn a pair, let the supervisor start
    waiting on both, then decide independently when (and with what exit code)
    each one "exits".
    """

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._returncode: int | None = None
        self._done = asyncio.Event()
        self.terminated = False
        """True once `terminate()` has been called at least once."""
        self.killed = False
        """True once `kill()` has been called at least once."""

    @property
    def pid(self) -> int:
        """The fake PID assigned to this process at spawn time."""
        return self._pid

    @property
    def returncode(self) -> int | None:
        """The exit code set by `complete()`, or None while still running."""
        return self._returncode

    async def wait(self) -> int:
        """Block until `complete()` is called, then return the given exit code."""
        await self._done.wait()
        assert self._returncode is not None
        return self._returncode

    def terminate(self) -> None:
        """Record that a graceful stop was requested; does not itself complete the process."""
        self.terminated = True

    def kill(self) -> None:
        """Record that a forceful stop was requested; does not itself complete the process."""
        self.killed = True

    def complete(self, returncode: int) -> None:
        """Simulate the process exiting with `returncode`, releasing any `wait()`ers.

        Raises `RuntimeError` if the process has already completed — a real
        process cannot exit twice, and a test relying on that would be
        asserting on a state that cannot occur in production.
        """
        if self._done.is_set():
            raise RuntimeError(f"FakeManagedProcess pid={self._pid} already completed")
        self._returncode = returncode
        self._done.set()


class FakeProcessSpawner:
    """Records every spawn and hands back a scriptable `FakeManagedProcess`.

    Each spawned process gets a distinct fake PID (a monotonically increasing
    counter starting at 1000) so tests can distinguish them without caring
    about real OS PID allocation.
    """

    def __init__(self) -> None:
        self.spawns: list[RecordedSpawn] = []
        """Every spawn call made against this instance, in order."""
        self.processes: list[FakeManagedProcess] = []
        """Every `FakeManagedProcess` handed back, in the same order as `spawns`."""
        self._pid_counter = itertools.count(1000)
        self._raise_on_next_spawn: Exception | None = None

    def raise_on_next_spawn(self, error: Exception) -> None:
        """Arrange for the next `spawn()` call to raise `error` instead of succeeding.

        Models a missing binary (`FileNotFoundError`) or a spawn-time
        `EADDRINUSE` (architecture §8 rule 6, §12.7).
        """
        self._raise_on_next_spawn = error

    async def spawn(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        name: str,
    ) -> FakeManagedProcess:
        """Record the call and return a new `FakeManagedProcess`, or raise if scripted."""
        if self._raise_on_next_spawn is not None:
            error, self._raise_on_next_spawn = self._raise_on_next_spawn, None
            raise error
        self.spawns.append(RecordedSpawn(argv=tuple(argv), env=dict(env), name=name))
        process = FakeManagedProcess(pid=next(self._pid_counter))
        self.processes.append(process)
        return process
