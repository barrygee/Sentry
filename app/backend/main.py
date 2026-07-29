"""Composition root: builds the FastAPI app and mounts every router (architecture §4.4).

Kept thin per the dependency rule — `routers -> services -> interfaces <- adapters`.
This module is the *only* place that chooses concrete adapters, constructs
every service, and wires them together via `AppContainer`; everything
downstream depends on the narrow Protocol or the already-built service, never
on how it was assembled.

Phase 2A's services (`services/device_registry`, `services/hotplug`,
`services/supervisor`, `services/eeprom`, `services/identity`,
`services/usb_discovery`, `services/event_bus`) are all implemented now, so
startup/shutdown below calls them directly and lets any failure — including a
stray `NotImplementedError` from something genuinely unfinished — crash
loudly rather than being swallowed. The transitional `except
NotImplementedError` guards this module previously carried while 2A was still
stubbed have been removed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.backend.adapters.asyncio_process import AsyncioProcessSpawner
from app.backend.adapters.composite_hotplug import CompositeHotplugSource
from app.backend.adapters.ctypes_rtlsdr import CtypesRtlSdrLibrary, RtlSdrLibraryUnavailableError
from app.backend.adapters.net import SocketPortProber
from app.backend.adapters.reconcile_hotplug import ReconcileHotplugSource
from app.backend.adapters.sysfs_usb import SysfsUsbDiscovery
from app.backend.adapters.system_clock import SystemClock
from app.backend.adapters.udev_netlink import UdevNetlinkHotplugSource
from app.backend.config import Settings, get_settings
from app.backend.db import create_sentry_engine, create_sentry_session_factory
from app.backend.example_fixtures import SENTRY_VERSION
from app.backend.interfaces.clock import Clock
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.interfaces.types import RtlSdrUsbStrings
from app.backend.repositories.device_repository import DeviceRepository
from app.backend.routers.api import api_router
from app.backend.services.control_follower import ControlFollowerService
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.eeprom import EepromService
from app.backend.services.event_bus import EventBus
from app.backend.services.health import HealthService
from app.backend.services.hotplug import HotplugService
from app.backend.services.port_allocator import PortAllocatorService
from app.backend.services.supervisor import SupervisorService
from app.backend.services.usb_discovery import UsbDiscoveryService

_logger = logging.getLogger(__name__)

# app/backend/main.py -> app/backend -> app -> repo root, where alembic.ini lives.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_DIST = _REPO_ROOT / "app" / "frontend" / "dist"


class _NullRtlSdrLibrary:
    """A `RtlSdrLibrary` reporting zero devices, for hosts with no `librtlsdr` installed.

    Constructing the real `CtypesRtlSdrLibrary` fails on a developer macOS
    laptop (and any container image missing `librtlsdr0`); rather than
    crashing the whole process at startup, Sentry degrades to "no dongles
    resolvable" — every spawn attempt then correctly reports
    `state_reason=index_unresolved` instead of the process refusing to boot at
    all. Production Pi images always install `librtlsdr0` (architecture §3.4),
    so `CtypesRtlSdrLibrary` is used there.
    """

    def device_count(self) -> int:
        """Always zero — no library is loaded to enumerate anything."""
        return 0

    def usb_strings(self, index: int) -> RtlSdrUsbStrings:
        """Always raises: there is never a valid index against zero devices."""
        raise IndexError(f"no RtlSdrLibrary loaded; index {index} does not exist")


def _build_rtlsdr_library() -> RtlSdrLibrary:
    """Construct the real ctypes-backed library, degrading to the null object if unavailable."""
    try:
        return CtypesRtlSdrLibrary()
    except RtlSdrLibraryUnavailableError:
        _logger.warning(
            "librtlsdr is unavailable on this host; RTL-SDR index resolution will always "
            "report index_unresolved. Expected on a developer workstation; install "
            "librtlsdr0 on the production Pi image."
        )
        return _NullRtlSdrLibrary()


def _run_migrations_sync(database_url: str) -> None:
    """Run `alembic upgrade head` synchronously against `database_url`.

    Called via `asyncio.to_thread` from the async lifespan, because Alembic's
    async env.py (`app/backend/alembic/env.py`) itself calls `asyncio.run()`
    internally, which cannot be invoked from within an already-running event
    loop (architecture §6.2: migrations run on every startup, unattended).
    """
    alembic_config = AlembicConfig(str(_REPO_ROOT / "alembic.ini"))
    # `env.py` re-derives the URL from `Settings` itself, but setting it here
    # too keeps this call self-contained and correct even if that changes.
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")


@dataclass
class AppContainer:
    """Every long-lived collaborator the HTTP layer depends on, built once at startup.

    Attached to `app.state.container`; routers reach it only through the
    `Depends()` accessors in `dependencies.py`, never directly.
    """

    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: EventBus
    device_registry: DeviceRegistry
    hotplug_service: HotplugService
    supervisor: SupervisorService
    control_follower: ControlFollowerService
    eeprom_service: EepromService
    port_allocator: PortAllocatorService
    health_service: HealthService
    background_tasks: list[asyncio.Task[None]]


def _build_container(settings: Settings) -> AppContainer:
    """Construct every adapter and service, wired per architecture §4.3/§4.4.

    Chooses the real, production adapters unconditionally — `_build_rtlsdr_library`
    is the sole documented exception, degrading gracefully rather than
    crashing on a host with no `librtlsdr`. Every seam remains overridable in
    tests via `app.dependency_overrides`, never by re-importing this function.
    """
    clock: Clock = SystemClock()
    engine = create_sentry_engine(settings)
    session_factory = create_sentry_session_factory(engine)
    # One process-wide `DeviceRepository`, backed by a session-per-call (see
    # that module's docstring) rather than one long-lived shared session —
    # `DeviceRegistry`'s background hotplug-consumer task and concurrent HTTP
    # request handlers (via `PortAllocatorService`) both call into it, and a
    # single `AsyncSession` is not safe for that kind of concurrent use.
    device_repository = DeviceRepository(session_factory)

    event_bus = EventBus(clock)
    device_registry = DeviceRegistry(device_repository, event_bus, clock)

    sysfs_root = Path(settings.sysfs_root)
    reconcile_discovery = SysfsUsbDiscovery(sysfs_root)
    hotplug_source = CompositeHotplugSource(
        primary_factory=lambda: UdevNetlinkHotplugSource(clock),
        fallback=ReconcileHotplugSource(reconcile_discovery, clock, settings.reconcile_interval_s),
    )
    usb_discovery_service = UsbDiscoveryService(SysfsUsbDiscovery(sysfs_root))
    hotplug_service = HotplugService(hotplug_source, usb_discovery_service, clock, event_bus)

    process_spawner = AsyncioProcessSpawner()
    rtlsdr_library = _build_rtlsdr_library()
    supervisor = SupervisorService(
        process_spawner=process_spawner,
        rtlsdr_library=rtlsdr_library,
        device_registry=device_registry,
        clock=clock,
        event_bus=event_bus,
        rtl_tcp_path=settings.rtl_tcp_path,
        relay_path=settings.relay_path,
        internal_port_base=settings.internal_port_base,
        max_devices=settings.max_devices,
    )
    control_follower = ControlFollowerService(device_registry, clock)
    eeprom_service = EepromService(
        process_spawner=process_spawner,
        rtlsdr_library=rtlsdr_library,
        supervisor=supervisor,
        device_registry=device_registry,
        rtl_eeprom_path=settings.rtl_eeprom_path,
    )
    port_allocator = PortAllocatorService(
        port_prober=SocketPortProber(),
        device_repository=device_repository,
        http_port=settings.http_port,
        internal_port_base=settings.internal_port_base,
        max_devices=settings.max_devices,
        operator_reserved_ports=settings.reserved_port_numbers(),
    )
    health_service = HealthService(
        device_registry=device_registry,
        hotplug=hotplug_service,
        started_at_ms=clock.now_ms(),
        version=SENTRY_VERSION,
    )

    return AppContainer(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        device_registry=device_registry,
        hotplug_service=hotplug_service,
        supervisor=supervisor,
        control_follower=control_follower,
        eeprom_service=eeprom_service,
        port_allocator=port_allocator,
        health_service=health_service,
        background_tasks=[],
    )


async def _run_hotplug_forever(container: AppContainer) -> None:
    """Background task: consume the hotplug stream for the process lifetime."""
    try:
        await container.hotplug_service.run()
    except asyncio.CancelledError:
        raise
    except Exception:
        _logger.exception("hotplug service crashed")


async def _run_supervisor_reconcile_loop(container: AppContainer) -> None:
    """Background task: re-run the supervisor's reconcile whenever the registry changes.

    `DeviceRegistry` already owns its own subscription to `HotplugService`'s
    internal `internal.device_arrived` / `internal.device_departed` messages
    (started from `DeviceRegistry.load()` — see that module's docstring), so
    this composition-root loop must **not** forward those same internal
    messages into the registry a second time; doing so was the original,
    reconciled-away seam bug here — both `main.py` and `device_registry.py`
    held their own subscription to the same internal messages, so every
    arrival/departure was applied twice. The one thing the registry cannot
    do for itself is re-run `SupervisorService.reconcile()` (it has no
    reference to the supervisor, by design — see architecture §4.3's
    dependency direction), so that is the sole responsibility left here:
    whenever the registry publishes a public `device_changed` /
    `device_removed` event, bring the running process set back in line with
    its desired set.
    """
    subscription = container.event_bus.subscribe()
    try:
        async for message in subscription:
            if message.event in ("device_changed", "device_removed"):
                await container.supervisor.reconcile()
    except asyncio.CancelledError:
        raise
    except Exception:
        _logger.exception("supervisor reconcile loop crashed")


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: migrate, load state, start background loops. Shutdown: reap everything.

    Shutdown order matters: background loops are cancelled first (so nothing
    keeps mutating the registry), then every supervised `rtl_tcp`+relay pair
    is terminated and, after a grace period, killed — no orphaned child
    process may survive `docker stop` — then the hotplug source and the
    database are closed last.
    """
    settings = get_settings()
    await asyncio.to_thread(_run_migrations_sync, settings.database_url)

    container = _build_container(settings)
    app.state.container = container

    await container.device_registry.load()
    await container.supervisor.reconcile()

    container.background_tasks.append(asyncio.create_task(_run_hotplug_forever(container)))
    container.background_tasks.append(
        asyncio.create_task(_run_supervisor_reconcile_loop(container))
    )

    try:
        yield
    finally:
        for task in container.background_tasks:
            task.cancel()
        for task in container.background_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        try:
            await container.hotplug_service.close()
        except Exception:
            _logger.exception("error closing hotplug service")

        try:
            await container.supervisor.stop_all()
        except Exception:
            _logger.exception("error stopping supervised processes")

        try:
            await container.device_registry.close()
        except Exception:
            _logger.exception("error closing device registry")

        await container.engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance.

    A factory (rather than a module-level `app = FastAPI()`) so tests can
    construct a fresh app with overridden settings/dependencies without
    import-order side effects.
    """
    settings = get_settings()
    application = FastAPI(
        title="Sentry",
        description="Multi-dongle RTL-SDR fleet manager for a Raspberry Pi.",
        version=SENTRY_VERSION,
        lifespan=_lifespan,
    )
    # CORS is closed by default (architecture §7.9): the SPA is same-origin in
    # production, and only an explicit SENTRY_CORS_ORIGINS list opens it for a
    # separately-hosted dev frontend. Never "*".
    cors_origins = settings.cors_origin_list()
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    application.include_router(api_router)

    # Static SPA mount goes last and at "/" so it never shadows `/api/**`:
    # Starlette matches routes in registration order, and the `/api` routes
    # above are registered first, so an `/api/...` request is served by them
    # before the catch-all static mount is ever consulted. Only mounted when
    # a build actually exists — a fresh checkout without `npm run build` still
    # serves the API alone rather than a confusing 404 from a missing directory.
    if _FRONTEND_DIST.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="spa",
        )
    return application


app = create_app()
