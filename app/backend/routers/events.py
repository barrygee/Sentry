"""`GET /api/events` — Server-Sent Events (architecture §7.3, ADR-0004).

Auth here uses `require_sse_bearer_token` rather than the standard header-only
dependency, because `EventSource` cannot set headers and so must additionally
be able to authenticate via `?access_token=` (architecture §7.9).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.backend.dependencies import (
    get_clock,
    get_device_registry,
    get_event_bus,
    get_health_service,
)
from app.backend.interfaces.clock import Clock
from app.backend.schemas.device import StatusResponse
from app.backend.security import require_sse_bearer_token
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.event_bus import RESYNC_EVENT_NAME, EventBus
from app.backend.services.health import HealthService

router = APIRouter(tags=["events"], dependencies=[Depends(require_sse_bearer_token)])

_logger = logging.getLogger(__name__)

HEALTH_HEARTBEAT_INTERVAL_S = 5.0
"""The `health` event is sent on this cadence, doubling as the SSE keepalive (architecture §7.3)."""

_PUBLIC_EVENT_NAMES = frozenset(
    {"snapshot", "device_changed", "device_removed", "health", "notice"}
)
"""The only event names architecture §7.3 permits onto a real SSE connection.

`EventBus.subscribe()` also carries internal-only messages
(`hotplug.HOTPLUG_DEVICE_ARRIVED_EVENT` / `HOTPLUG_DEVICE_DEPARTED_EVENT`,
consumed only by `DeviceRegistry`) and the `RESYNC_EVENT_NAME` overflow
marker — neither is ever a valid wire event, and both must be filtered out
here before anything reaches a browser (architecture §7.3, `event_bus.py`
module docstring). This is a hard security/correctness boundary, not a
cosmetic one: leaking an internal event name onto the wire would expose
implementation details of the hotplug pipeline to any client holding (or
guessing) the SSE URL.
"""


def _format_sse(event_name: str, payload: Any) -> str:
    """Format one named SSE frame: `event: <name>\\ndata: <json>\\n\\n`."""
    data = payload.model_dump() if isinstance(payload, BaseModel) else payload
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"


async def _event_stream(
    device_registry: DeviceRegistry,
    event_bus: EventBus,
    health_service: HealthService,
    clock: Clock,
) -> AsyncIterator[str]:
    """The full named-event stream: `retry:`, an immediate `snapshot`, then the live bus.

    A `health` event is additionally injected every `HEALTH_HEARTBEAT_INTERVAL_S`
    regardless of bus activity, so a quiet fleet still keeps the connection
    alive. `Last-Event-ID` is deliberately never read here (architecture
    §7.3): there is no replay buffer, so every connection — including a
    browser's native reconnect — gets a fresh `snapshot` rather than a
    replayed delta log.
    """
    yield "retry: 3000\n\n"
    snapshot = StatusResponse(generated_at=clock.now_ms(), sdrs=device_registry.list_statuses())
    yield _format_sse("snapshot", snapshot)

    subscription = event_bus.subscribe()
    pending_next: asyncio.Task[Any] | None = None
    next_health_at = clock.monotonic() + HEALTH_HEARTBEAT_INTERVAL_S
    try:
        while True:
            timeout = max(0.0, next_health_at - clock.monotonic())
            if pending_next is None:
                pending_next = asyncio.ensure_future(subscription.__anext__())
            done, _pending = await asyncio.wait({pending_next}, timeout=timeout)
            if pending_next in done:
                finished_task, pending_next = pending_next, None
                try:
                    message = finished_task.result()
                except StopAsyncIteration:
                    return
                if message.event == RESYNC_EVENT_NAME:
                    # A subscriber queue overflowed and dropped a message;
                    # self-heal with a freshly-built snapshot rather than
                    # ever relaying this internal marker onto the wire.
                    resync_snapshot = StatusResponse(
                        generated_at=clock.now_ms(), sdrs=device_registry.list_statuses()
                    )
                    yield _format_sse("snapshot", resync_snapshot)
                elif message.event in _PUBLIC_EVENT_NAMES:
                    yield _format_sse(message.event, message.data)
                else:
                    # Internal-only event (e.g. hotplug's
                    # internal.device_arrived/departed) — never forwarded to
                    # a browser (architecture §7.3).
                    _logger.debug("dropping internal-only event %r from SSE stream", message.event)
            else:
                health_snapshot = await health_service.get_health()
                yield _format_sse("health", health_snapshot)
                next_health_at = clock.monotonic() + HEALTH_HEARTBEAT_INTERVAL_S
    finally:
        if pending_next is not None:
            pending_next.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending_next
        aclose = getattr(subscription, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()


@router.get("/events", summary="Realtime fleet events (Server-Sent Events)")
async def get_events(
    device_registry: DeviceRegistry = Depends(get_device_registry),
    event_bus: EventBus = Depends(get_event_bus),
    health_service: HealthService = Depends(get_health_service),
    clock: Clock = Depends(get_clock),
) -> StreamingResponse:
    """Open an SSE stream of fleet events.

    The response is `text/event-stream` and is not one flat JSON schema — the
    frozen shape of each named event is documented in `schemas/device.py`,
    `schemas/events.py` and `schemas/health.py`. Client disconnect cancels the
    underlying generator (Starlette's normal `StreamingResponse` behaviour),
    which the `finally` block above uses to release the bus subscription.
    """
    return StreamingResponse(
        _event_stream(device_registry, event_bus, health_service, clock),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
