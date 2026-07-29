"""HTTP routers — one `APIRouter` per resource, aggregated under `/api` (architecture §4.4).

Routers are thin: validate via the schema, call a service, map the result to
a response schema, return. No business logic, no direct adapter or ORM
access. In Phase 0 every handler returns a fixed, correctly-typed example
response so `openapi.json` generates accurately without a working backend.
"""
