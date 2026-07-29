"""Pydantic request/response schemas — the frozen API contract (architecture §7).

Schemas format JSON for HTTP; they are explicitly not services (architecture
§4.3) and never contain business logic beyond field-level validation.
"""
