"""FastAPI dependency-injection accessors for the composition root (architecture §4.4).

Every router pulls its collaborators through these thin `Depends()` callables
rather than importing `main.py`'s container directly — this is what keeps the
dependency rule intact (`routers -> services -> interfaces <- adapters`):
routers depend on already-constructed services, never on how they were built.

Each accessor reads from `request.app.state.container`, the single
`AppContainer` instance `main.create_app()` builds once at startup. Tests
substitute fakes via `app.dependency_overrides[get_x] = lambda: fake_x`
rather than by monkeypatching this module.
"""

from __future__ import annotations

from fastapi import Request

from app.backend.config import Settings
from app.backend.interfaces.clock import Clock
from app.backend.services.console_auth import ConsoleAuthService
from app.backend.services.control_follower import ControlFollowerService
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.eeprom import EepromService
from app.backend.services.event_bus import EventBus
from app.backend.services.health import HealthService
from app.backend.services.host_control_settings import HostControlSettingsService
from app.backend.services.hotspot import HotspotService
from app.backend.services.port_allocator import PortAllocatorService
from app.backend.services.supervisor import SupervisorService


def get_settings_dependency(request: Request) -> Settings:
    """Return the process-wide `Settings` the container was built from."""
    settings: Settings = request.app.state.container.settings
    return settings


def get_clock(request: Request) -> Clock:
    """Return the process-wide `Clock`."""
    clock: Clock = request.app.state.container.clock
    return clock


def get_device_registry(request: Request) -> DeviceRegistry:
    """Return the single, process-wide `DeviceRegistry` — the source of truth every router reads."""
    registry: DeviceRegistry = request.app.state.container.device_registry
    return registry


def get_health_service(request: Request) -> HealthService:
    """Return the process-wide `HealthService`."""
    health_service: HealthService = request.app.state.container.health_service
    return health_service


def get_event_bus(request: Request) -> EventBus:
    """Return the process-wide `EventBus` SSE subscribers attach to."""
    event_bus: EventBus = request.app.state.container.event_bus
    return event_bus


def get_port_allocator(request: Request) -> PortAllocatorService:
    """Return the process-wide `PortAllocatorService`."""
    port_allocator: PortAllocatorService = request.app.state.container.port_allocator
    return port_allocator


def get_eeprom_service(request: Request) -> EepromService:
    """Return the process-wide `EepromService`."""
    eeprom_service: EepromService = request.app.state.container.eeprom_service
    return eeprom_service


def get_supervisor(request: Request) -> SupervisorService:
    """Return the process-wide `SupervisorService`."""
    supervisor: SupervisorService = request.app.state.container.supervisor
    return supervisor


def get_console_auth_service(request: Request) -> ConsoleAuthService:
    """Return the process-wide `ConsoleAuthService` (ADR-0010)."""
    console_auth_service: ConsoleAuthService = request.app.state.container.console_auth_service
    return console_auth_service


def get_host_control_settings(request: Request) -> HostControlSettingsService:
    """Return the process-wide `HostControlSettingsService` (ADR-0013)."""
    host_control_settings: HostControlSettingsService = (
        request.app.state.container.host_control_settings
    )
    return host_control_settings


def get_hotspot_service(request: Request) -> HotspotService:
    """Return the process-wide `HotspotService`."""
    hotspot_service: HotspotService = request.app.state.container.hotspot_service
    return hotspot_service


def get_control_follower(request: Request) -> ControlFollowerService:
    """Return the process-wide `ControlFollowerService`."""
    control_follower: ControlFollowerService = request.app.state.container.control_follower
    return control_follower
