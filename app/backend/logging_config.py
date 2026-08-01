"""Uvicorn logging configuration with the SSE bearer token redacted (architecture §7.9).

`security.py`'s `require_sse_bearer_token` accepts `GET /api/events` with the
token as `?access_token=...` because `EventSource` cannot set headers. That
docstring previously *claimed* query strings were stripped from uvicorn's
access log — no such configuration existed anywhere in the codebase, so every
SSE connection wrote the sole API credential to stdout, `docker logs`, and
journald verbatim. This module is that configuration, actually wired in by
`run_server.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from uvicorn.logging import AccessFormatter


class RedactingAccessFormatter(AccessFormatter):
    """`uvicorn.logging.AccessFormatter`, with any query string stripped from the request line.

    Uvicorn's `AccessFormatter.formatMessage` reads `record.args` as the
    5-tuple `(client_addr, method, full_path, http_version, status_code)`
    (`uvicorn/logging.py`) — `full_path` is the only element that can carry a
    query string, so this subclass rewrites just that element, in place, on
    `record.args` before delegating to the real formatter.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:
        """Redact `record.args[2]`'s query string, then format exactly as the base class would."""
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            client_addr, method, full_path, http_version, status_code = args
            if isinstance(full_path, str) and "?" in full_path:
                full_path = full_path.split("?", 1)[0] + "?[redacted]"
                record.args = (client_addr, method, full_path, http_version, status_code)
        return super().formatMessage(record)


SENTRY_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": None,
        },
        "access": {
            "()": "app.backend.logging_config.RedactingAccessFormatter",
            "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}
"""A copy of `uvicorn.config.LOGGING_CONFIG` with only the `access` formatter
class swapped for `RedactingAccessFormatter` — every other handler/logger
entry is unchanged so behaviour otherwise matches uvicorn's own default."""
