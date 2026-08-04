"""Aggregates every domain router under `/api` (architecture §4.4).

One `include_router` call per resource — never a single monolithic router.
`GET /api/v1/sdrs` and its `/api/sdrs` alias live outside the `/api` prefix
here because `sdrs.router` already declares its own full paths.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.backend.routers import devices, events, health, hotspot, sdrs, status

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(status.router)
api_router.include_router(events.router)
api_router.include_router(devices.router)
api_router.include_router(sdrs.router)
api_router.include_router(hotspot.router)
