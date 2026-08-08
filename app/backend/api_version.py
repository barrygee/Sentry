"""The management API's version, and the header that advertises it.

## Why this exists

Sentry's `/api` surface used to have exactly one consumer — its own SPA, shipped
in the same image, so it was unversioned and free to change between releases
(architecture §7). That is no longer true. Sentinel now drives device
configuration and the hotspot over these same routes (ADR-0009), and the two
are deployed and upgraded independently: a Pi can sit on an older Sentry for
months after Sentinel has moved on.

So the management API is now a **contract with a second party**, and a consumer
needs to be able to tell which one it is talking to before it relies on a field
being there.

## What the number means

`MANAGEMENT_API_VERSION` is a single integer, bumped only on a **breaking**
change — a removed or renamed field, a changed type, a route that moves or
stops accepting what it used to. Additive changes (a new optional field, a new
route, a new enum member on a field a consumer already tolerates) do **not**
bump it, and consumers must ignore fields they do not recognise.

This is deliberately not semver. There is one dimension a client actually needs
to branch on — "can I still parse this?" — and a two- or three-part version
invites clients to branch on the parts that never mattered.

Note this is a *different* number from `SDR_EXPORT_API_VERSION` in
`schemas/sdr_export.py`, which versions the narrow public `GET /api/v1/sdrs`
export. That one is consumed by any Sentinel; this one covers the management
routes behind the auth token. They version independently and are advertised in
separate headers, because a breaking change to device configuration has no
bearing on the published SDR list and vice versa.
"""

from __future__ import annotations

from typing import Any

MANAGEMENT_API_VERSION = 1
"""Bumped only on a breaking change to the management API. See the module docstring."""

MANAGEMENT_API_VERSION_HEADER = "X-Sentry-Api-Version"
"""Carried on every `/api` response, including error responses."""

_HEADER_NAME_BYTES = MANAGEMENT_API_VERSION_HEADER.lower().encode("ascii")
_HEADER_VALUE_BYTES = str(MANAGEMENT_API_VERSION).encode("ascii")


class ManagementApiVersionMiddleware:
    """Stamps `X-Sentry-Api-Version` on every `/api` response.

    Middleware rather than a router-level dependency, because a dependency that
    mutates the injected `Response` only reaches responses a handler *returned*.
    An `HTTPException` is rendered by the exception handler into a fresh
    response the dependency never sees — so exactly the 4xx/5xx replies a client
    most needs to interpret against a known version would have arrived without
    one.

    Raw ASGI rather than `@app.middleware("http")`, for the reason
    `ReferrerPolicyMiddleware` documents at length: `BaseHTTPMiddleware`
    re-drives the response through its own machinery and breaks the long-lived
    `StreamingResponse` behind `GET /api/events`. Touching only the
    `http.response.start` headers passes every `http.response.body` message
    through untouched.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api"):
            await self._app(scope, receive, send)
            return

        async def _send_with_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((_HEADER_NAME_BYTES, _HEADER_VALUE_BYTES))
            await send(message)

        await self._app(scope, receive, _send_with_header)
