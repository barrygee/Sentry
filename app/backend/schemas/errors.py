"""The uniform error envelope used by every endpoint (architecture §7).

All Sentry errors use `{"detail": {"code": ..., "message": ..., ...context}}`
so a client has exactly one shape to parse regardless of status code. Routers
raise `fastapi.HTTPException(status_code=..., detail=ErrorDetail(...).model_dump())`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """The machine-readable core of an error response; subclassed per error for extra context."""

    model_config = ConfigDict(extra="allow", frozen=True)

    code: str
    message: str


class ErrorResponse(BaseModel):
    """The full response body FastAPI serializes for a raised `HTTPException`."""

    model_config = ConfigDict(frozen=True)

    detail: ErrorDetail


def error_detail(code: str, message: str, **context: object) -> dict[str, object]:
    """Build the uniform `{"code", "message", ...context}` dict for `HTTPException(detail=...)`.

    A plain dict (not an `ErrorDetail` instance) because `HTTPException.detail`
    is serialized as-is by FastAPI's exception handler; constructing the
    Pydantic model here would just be dumped again for no benefit.
    """
    return {"code": code, "message": message, **context}
