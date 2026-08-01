"""Process entrypoint: runs uvicorn driven entirely by `Settings` (architecture §3.4).

Two problems this module fixes by existing at all:

1. **`SENTRY_HTTP_HOST`/`SENTRY_HTTP_PORT` were dead configuration.** The
   Dockerfile's `CMD` previously hardcoded `uvicorn ... --host 0.0.0.0 --port
   8000` directly, so `SENTRY_HTTP_HOST=127.0.0.1` (documented in
   `.env.example`/`docker-compose.yml` as a way to bind only to loopback
   behind a reverse proxy) was silently ignored. Driving uvicorn's bind
   address/port from the same `Settings` object the rest of the app reads
   makes the documented variables actually work, and keeps
   `settings.http_port` (also used to reserve the port in
   `PortAllocatorService`) consistent with what uvicorn actually binds.
2. **The SSE token leaked into the access log on every startup path.** Only
   passing `--log-config` on an ad-hoc CLI invocation would fix this
   inconsistently; wiring `SENTRY_LOGGING_CONFIG` (`logging_config.py`) in
   here means every way this process starts (`python -m
   app.backend.run_server`, imported and called directly in a dev shell)
   gets the redacting formatter for free.
"""

from __future__ import annotations

import uvicorn

from app.backend.config import get_settings
from app.backend.logging_config import SENTRY_LOGGING_CONFIG


def main() -> None:
    """Start uvicorn serving `app.backend.main:app`, bound and logged per `Settings`."""
    settings = get_settings()
    uvicorn.run(
        "app.backend.main:app",
        host=settings.http_host,
        port=settings.http_port,
        log_config=SENTRY_LOGGING_CONFIG,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
