"""A controllable, in-memory `Clock` double for deterministic tests.

Advances only when told to, so backoff schedules, debounce windows and
restart-budget accounting can be asserted exactly without a test sleeping in
wall-clock time (architecture §4.1, §12.7).
"""

from __future__ import annotations

import asyncio


class FakeClock:
    """A `Clock` whose wall-clock and monotonic readings are advanced explicitly.

    Both `now_ms()` and `monotonic()` are derived from the same internal
    counter, so a test that calls `advance()` sees both move together.
    `sleep()` returns as soon as the requested duration has elapsed on this
    internal clock, allowing an `await clock.sleep(60)` to complete instantly
    once the test calls `advance(60)` from another task, or immediately if
    the caller advances before awaiting.
    """

    def __init__(self, start_ms: int = 0) -> None:
        """Start the fake clock at `start_ms` Unix milliseconds (default epoch)."""
        self._now_ms = start_ms
        self._monotonic_s = start_ms / 1000
        self._waiters: list[tuple[float, asyncio.Event]] = []

    def now_ms(self) -> int:
        """Return the current fake wall-clock time as Unix milliseconds."""
        return self._now_ms

    def monotonic(self) -> float:
        """Return the current fake monotonic reading in seconds."""
        return self._monotonic_s

    def advance(self, seconds: float) -> None:
        """Move both the wall-clock and monotonic readings forward by `seconds`.

        Wakes any `sleep()` calls whose deadline has now passed.
        """
        self._now_ms += int(seconds * 1000)
        self._monotonic_s += seconds
        still_waiting: list[tuple[float, asyncio.Event]] = []
        for deadline, event in self._waiters:
            if deadline <= self._monotonic_s:
                event.set()
            else:
                still_waiting.append((deadline, event))
        self._waiters = still_waiting

    async def sleep(self, seconds: float) -> None:
        """Suspend until `advance()` has moved the fake clock past this deadline.

        A non-positive `seconds` returns immediately, matching `asyncio.sleep`.
        """
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        deadline = self._monotonic_s + seconds
        event = asyncio.Event()
        self._waiters.append((deadline, event))
        await event.wait()
