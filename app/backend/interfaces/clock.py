"""Time seam so backoff, debounce and cooldown logic is deterministic in tests.

Every service that sleeps, measures elapsed time, or stamps a timestamp takes
a `Clock` by constructor injection rather than calling `time`/`asyncio.sleep`
directly, so `tests/fakes/FakeClock` can advance time instantly and
deterministically instead of a test suite sleeping in wall-clock time.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Time and sleep, abstracted for testability."""

    def now_ms(self) -> int:
        """Return the current wall-clock time as Unix milliseconds.

        Used for persisted and displayed timestamps (`state_since`,
        `last_seen_at`, and similar). Not guaranteed monotonic.
        """
        ...

    def monotonic(self) -> float:
        """Return a monotonic clock reading in seconds, for measuring durations.

        Used for backoff scheduling, debounce windows and restart-budget
        accounting, none of which may be affected by wall-clock adjustments.
        """
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend the current task for `seconds`."""
        ...
