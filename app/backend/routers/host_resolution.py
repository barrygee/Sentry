"""Resolution of the LAN host Sentry publishes to consumers (architecture §7.7).

`DeviceRegistry` cannot resolve this itself — it depends on
`SENTRY_ADVERTISED_HOST` or the current request's `Host` header, neither of
which the service layer has access to — so every `DeviceStatus.output` it
builds carries `host=""` and the routers overlay the real value before
serialising. This module is that overlay, shared by `/api/status`,
`/api/events` and `/api/v1/sdrs` so the three can never disagree.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from fastapi import Request

from app.backend.config import Settings
from app.backend.schemas.device import DeviceStatus

# A plain hostname or IPv4 literal. Deliberately strict: see `resolve_public_host`.
VALID_HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")


def resolve_public_host(request: Request, settings: Settings) -> str:
    """Resolve the LAN host to publish.

    `SENTRY_ADVERTISED_HOST` wins when set; otherwise the request's `Host`
    header with any port suffix stripped. Never `0.0.0.0` (the bind address)
    and never a container-internal address — a consumer dials this value from
    another machine, so an unparseable or absent `Host` falls back to
    `localhost` rather than something unreachable.

    **Why the header is validated, not merely parsed.** `Host` is entirely
    client-controlled; without `SENTRY_ADVERTISED_HOST` set, a forged header
    would otherwise be reflected verbatim into every consumer's host field,
    pointing them at an address of the sender's choosing. Restricting the
    fallback to something already shaped like a hostname/IPv4 literal does not
    close that hole completely — operators who need it closed should set
    `SENTRY_ADVERTISED_HOST` — but it does stop the header carrying a scheme,
    credentials, control characters, or an implausibly long value.
    """
    if settings.advertised_host:
        return settings.advertised_host
    host_header = request.headers.get("host", "")
    hostname = host_header.rsplit(":", 1)[0].strip()
    if hostname and VALID_HOSTNAME_PATTERN.match(hostname):
        return hostname
    return "localhost"


def with_resolved_host(device_status: DeviceStatus, host: str) -> DeviceStatus:
    """Return `device_status` with its `output.host` set to `host`.

    A device with no assigned output port has no `output` block at all, and is
    returned unchanged.
    """
    if device_status.output is None:
        return device_status
    return device_status.model_copy(
        update={"output": device_status.output.model_copy(update={"host": host})}
    )


def with_resolved_hosts(
    device_statuses: Sequence[DeviceStatus], host: str
) -> tuple[DeviceStatus, ...]:
    """Apply `with_resolved_host` across a full status collection.

    Takes any sequence and returns a tuple, matching both
    `DeviceRegistry.list_statuses()` and `StatusResponse.sdrs`, so the status
    payload stays immutable end to end.
    """
    return tuple(with_resolved_host(device_status, host) for device_status in device_statuses)
