"""Real `Clock` implementation backed by the standard library (architecture §4.2).

The only production implementation of the `Clock` Protocol. Tests use
`tests.fakes.clock.FakeClock` instead so backoff, debounce and cooldown logic
never depends on wall-clock sleeps.
"""

from __future__ import annotations

import asyncio
import time


class SystemClock:
    """`Clock` backed by `time.time`, `time.monotonic` and `asyncio.sleep`."""

    def now_ms(self) -> int:
        """Return the current wall-clock time as Unix milliseconds."""
        return int(time.time() * 1000)

    def monotonic(self) -> float:
        """Return a monotonic clock reading in seconds."""
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """Suspend the current task for `seconds` using `asyncio.sleep`."""
        await asyncio.sleep(seconds)
