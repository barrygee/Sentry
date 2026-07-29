"""Composite `HotplugSource`: udev primary + sysfs-reconcile fallback.

Merges both streams and de-duplicates a `(action, topology_path)` pair seen
from both sources within a 1 s window down to one event. If the primary
cannot even be constructed (no netlink available — macOS, and some
containers), this degrades cleanly to reconcile-only and reports that in
`degraded_to_reconcile_only` for `GET /api/health`'s `hotplug.source` field
(architecture §4.2).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

from app.backend.interfaces.types import HotplugEvent
from app.backend.interfaces.usb import HotplugSource

_logger = logging.getLogger(__name__)

DEDUPE_WINDOW_S = 1.0
"""The same (action, topology_path) from both sources within this window counts as one event."""


class CompositeHotplugSource:
    """Merges a primary `HotplugSource` (udev) with a fallback (sysfs reconcile).

    The primary is constructed lazily, inside this class's constructor, via
    `primary_factory` — so a platform where netlink is unavailable (macOS, or
    a container without `CAP_NET_ADMIN`) raises immediately here rather than
    on first use, and this class catches that and runs on the fallback alone.
    """

    def __init__(
        self,
        primary_factory: Callable[[], HotplugSource],
        fallback: HotplugSource,
    ) -> None:
        """`primary_factory` is called once; any exception degrades to fallback-only."""
        self._fallback = fallback
        self._primary: HotplugSource | None
        try:
            self._primary = primary_factory()
        except Exception:
            _logger.warning(
                "primary hotplug source unavailable, falling back to reconcile-only",
                exc_info=True,
            )
            self._primary = None
        self._closed = False

    @property
    def degraded_to_reconcile_only(self) -> bool:
        """True when the primary source could not be constructed or has failed.

        Surfaced by the consuming service as `GET /api/health`'s
        `hotplug.source: "reconcile"` / `hotplug.healthy: false`.
        """
        return self._primary is None

    async def events(self) -> AsyncIterator[HotplugEvent]:
        """Yield the merged, de-duplicated event stream from both sources.

        When the primary is unavailable, this is simply the fallback's
        stream. When both are running, events from either are yielded as
        they arrive; a duplicate `(action, topology_path)` observed from the
        second source within `DEDUPE_WINDOW_S` of the first is suppressed.
        """
        if self._primary is None:
            async for event in self._fallback.events():
                yield event
            return

        queue: asyncio.Queue[HotplugEvent | None] = asyncio.Queue()

        async def _pump(source: HotplugSource) -> None:
            try:
                async for event in source.events():
                    await queue.put(event)
            finally:
                await queue.put(None)

        pump_tasks = [
            asyncio.create_task(_pump(self._primary)),
            asyncio.create_task(_pump(self._fallback)),
        ]
        active_sources = len(pump_tasks)
        last_seen_at: dict[tuple[str, str], float] = {}
        try:
            while active_sources > 0 and not self._closed:
                queued_event = await queue.get()
                if queued_event is None:
                    active_sources -= 1
                    continue
                dedupe_key = (queued_event.action, queued_event.topology_path)
                last_seen = last_seen_at.get(dedupe_key)
                last_seen_at[dedupe_key] = queued_event.observed_at_ms / 1000
                if last_seen is not None and (
                    queued_event.observed_at_ms / 1000 - last_seen <= DEDUPE_WINDOW_S
                ):
                    continue
                yield queued_event
        finally:
            for task in pump_tasks:
                task.cancel()
            await asyncio.gather(*pump_tasks, return_exceptions=True)

    def close(self) -> None:
        """Close both underlying sources (whichever are present)."""
        self._closed = True
        if self._primary is not None:
            self._primary.close()
        self._fallback.close()
