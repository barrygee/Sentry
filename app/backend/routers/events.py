"""`GET /api/events` — Server-Sent Events (architecture §7.3, ADR-0004).

Auth is the same session dependency every other management route uses. It was
once a special case: `EventSource` cannot set an `Authorization` header, so the
bearer token had to be accepted from `?access_token=` — writing a credential
into browser history and, but for a bespoke uvicorn log format, the access log.
The session cookie (ADR-0010) is sent automatically on same-origin requests, so
that exception is deleted rather than mitigated.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.backend.config import Settings
from app.backend.dependencies import (
    get_clock,
    get_device_registry,
    get_event_bus,
    get_health_service,
    get_sentry_location_service,
    get_settings_dependency,
)
from app.backend.interfaces.clock import Clock
from app.backend.routers.host_resolution import (
    resolve_public_host,
    with_resolved_host,
    with_resolved_hosts,
)
from app.backend.schemas.device import DeviceStatus, StatusResponse
from app.backend.schemas.errors import error_detail
from app.backend.security import require_console_session
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.event_bus import RESYNC_EVENT_NAME, EventBus
from app.backend.services.health import HealthService
from app.backend.services.sentry_location import SentryLocationService

router = APIRouter(tags=["events"], dependencies=[Depends(require_console_session)])

_logger = logging.getLogger(__name__)

HEALTH_HEARTBEAT_INTERVAL_S = 5.0
"""The `health` event is sent on this cadence, doubling as the SSE keepalive (architecture §7.3)."""

MAX_SSE_SUBSCRIBERS = 64
"""`EventBus` itself keeps an uncapped subscriber set — every one gets its own
bounded queue and its own `HEALTH_HEARTBEAT_INTERVAL_S`-cadence heartbeat, so
an unbounded number of open connections is an unbounded amount of ongoing
work with no natural backpressure. A Sentry deployment is one operator's LAN
console plus, at most, a handful of dashboards; 64 is generously above any
legitimate use and cheap to raise later if that assumption turns out wrong."""

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
    location_service: SentryLocationService,
    public_host: str,
) -> AsyncIterator[str]:
    """The full named-event stream: `retry:`, an immediate `snapshot`, then the live bus.

    A `health` event is additionally injected every `HEALTH_HEARTBEAT_INTERVAL_S`
    regardless of bus activity, so a quiet SDR still keeps the connection
    alive. `Last-Event-ID` is deliberately never read here (architecture
    §7.3): there is no replay buffer, so every connection — including a
    browser's native reconnect — gets a fresh `snapshot` rather than a
    replayed delta log.
    """
    yield "retry: 3000\n\n"
    # `public_host` is resolved once per connection from the request that opened
    # it: the registry emits `output.host=""` because it cannot know the
    # publishable address (architecture §7.7), so it is overlaid on every
    # DeviceStatus leaving this stream.
    # Read per snapshot rather than once per connection: an operator can move
    # the position from Settings while a stream is open, and a resync below must
    # then carry the new one rather than the value this connection opened with.
    snapshot = StatusResponse(
        generated_at=clock.now_ms(),
        location=await location_service.get_location(),
        sdrs=with_resolved_hosts(device_registry.list_statuses(), public_host),
    )
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
                        generated_at=clock.now_ms(),
                        location=await location_service.get_location(),
                        sdrs=with_resolved_hosts(device_registry.list_statuses(), public_host),
                    )
                    yield _format_sse("snapshot", resync_snapshot)
                elif message.event in _PUBLIC_EVENT_NAMES:
                    payload = message.data
                    if isinstance(payload, DeviceStatus):
                        payload = with_resolved_host(payload, public_host)
                    yield _format_sse(message.event, payload)
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


@router.get("/events", summary="Realtime SDR events (Server-Sent Events)")
async def get_events(
    request: Request,
    device_registry: DeviceRegistry = Depends(get_device_registry),
    event_bus: EventBus = Depends(get_event_bus),
    health_service: HealthService = Depends(get_health_service),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings_dependency),
    location_service: SentryLocationService = Depends(get_sentry_location_service),
) -> StreamingResponse:
    """Open an SSE stream of SDR events.

    The response is `text/event-stream` and is not one flat JSON schema — the
    frozen shape of each named event is documented in `schemas/device.py`,
    `schemas/events.py` and `schemas/health.py`. Client disconnect cancels the
    underlying generator (Starlette's normal `StreamingResponse` behaviour),
    which the `finally` block above uses to release the bus subscription.

    Refuses a new connection with `503` once `MAX_SSE_SUBSCRIBERS` are
    already open, rather than accepting an unbounded number of concurrent
    streams (each with its own queue and heartbeat timer).
    """
    if event_bus.subscriber_count() >= MAX_SSE_SUBSCRIBERS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(
                "too_many_subscribers", "Too many concurrent event streams; try again shortly."
            ),
        )
    return StreamingResponse(
        _event_stream(
            device_registry,
            event_bus,
            health_service,
            clock,
            location_service,
            resolve_public_host(request, settings),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
