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
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.responses import Response
from starlette.types import Scope

from app.backend.adapters.asyncio_process import AsyncioProcessSpawner
from app.backend.adapters.composite_hotplug import CompositeHotplugSource
from app.backend.adapters.ctypes_rtlsdr import CtypesRtlSdrLibrary, RtlSdrLibraryUnavailableError
from app.backend.adapters.net import SocketPortProber
from app.backend.adapters.nmcli_wifi_ap import NmcliWifiApController, UnavailableWifiApController
from app.backend.adapters.reconcile_hotplug import ReconcileHotplugSource
from app.backend.adapters.sysfs_usb import SysfsUsbDiscovery
from app.backend.adapters.system_clock import SystemClock
from app.backend.adapters.udev_netlink import UdevNetlinkHotplugSource
from app.backend.config import Settings, get_settings
from app.backend.db import create_sentry_engine, create_sentry_session_factory
from app.backend.example_fixtures import SENTRY_VERSION
from app.backend.interfaces.clock import Clock
from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.rtlsdr import RtlSdrLibrary
from app.backend.interfaces.types import RtlSdrUsbStrings
from app.backend.interfaces.wifi_ap import WifiApController
from app.backend.repositories.device_repository import DeviceRepository
from app.backend.routers.api import api_router
from app.backend.services.control_follower import ControlFollowerService
from app.backend.services.device_registry import DeviceRegistry
from app.backend.services.eeprom import EepromService
from app.backend.services.event_bus import EventBus
from app.backend.services.health import HealthService
from app.backend.services.hotplug import HotplugService
from app.backend.services.hotspot import HotspotService
from app.backend.services.port_allocator import PortAllocatorService
from app.backend.services.supervisor import SupervisorService
from app.backend.services.usb_discovery import UsbDiscoveryService

_logger = logging.getLogger(__name__)

# app/backend/main.py -> app/backend -> app -> repo root, where alembic.ini lives.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_DIST = _REPO_ROOT / "app" / "frontend" / "dist"


class CacheAwareSpaStaticFiles(StaticFiles):
    """Serves the built SPA with cache headers that match how Vite names files.

    Vite content-hashes every JS/CSS asset (`index-GcUORenv.css`), so those are
    immutable: a changed file gets a new name, and the old name is never reused.
    They can be cached for a year.

    `index.html` is the exception and the reason this class exists. It is the
    one file with a stable name, and it is what *points at* the hashed assets.
    Served with default headers a browser may reuse a cached copy indefinitely,
    pinning the app to the previous deploy's asset names — the UI simply does
    not change after an upgrade, with no error anywhere to explain why. Serving
    it `no-cache` means the browser must revalidate it on every load, so a new
    deploy is picked up immediately while the (usually much larger) hashed
    assets still come from cache.

    `no-cache` is deliberate rather than `no-store`: it permits a conditional
    request, so an unchanged index still answers 304 rather than resending.
    """

    IMMUTABLE_SUFFIXES = (".js", ".css", ".woff2", ".woff", ".svg", ".png", ".jpg", ".webp")

    def file_response(
        self,
        full_path: PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """Delegate to Starlette, then set `Cache-Control` from the file's extension."""
        response = super().file_response(full_path, stat_result, scope, status_code)
        path_name = str(full_path)
        if path_name.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        elif path_name.endswith(self.IMMUTABLE_SUFFIXES):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


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

    def is_available(self) -> bool:
        """Always `False` — no real `librtlsdr` was ever loaded."""
        return False

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


DBUS_SYSTEM_BUS_SOCKET = Path("/run/dbus/system_bus_socket")
"""The host's system D-Bus socket, which `nmcli` needs to reach NetworkManager.

Present only when compose mounts it (ADR-0007). Its absence is the normal state
on a developer workstation and on any deployment that has not opted into
hotspot control, so it degrades rather than failing."""


def _build_wifi_ap_controller(
    settings: Settings, process_spawner: ProcessSpawner
) -> WifiApController:
    """Construct the real nmcli-backed controller, degrading to the null object.

    Follows `_build_rtlsdr_library`'s precedent exactly: an optional capability
    the host may simply not have must never crash startup. Three things have to
    be true for real control — the operator enabled it, `nmcli` exists, and the
    host's D-Bus socket is reachable — and each failing case names itself in the
    log so an operator on the Pi knows which one to fix.
    """
    if not settings.hotspot_control_enabled:
        return UnavailableWifiApController(
            "Hotspot control is switched off (SENTRY_HOTSPOT_CONTROL_ENABLED).",
            nm_state_root=Path(settings.nm_state_root),
        )
    if shutil.which(settings.nmcli_path) is None:
        _logger.warning(
            "hotspot control is enabled but %s was not found; the hotspot API will report "
            "available=false. Expected on a developer workstation; install the "
            "network-manager package in the production image.",
            settings.nmcli_path,
        )
        return UnavailableWifiApController(
            f"{settings.nmcli_path} is not installed.",
            nm_state_root=Path(settings.nm_state_root),
        )
    if not DBUS_SYSTEM_BUS_SOCKET.exists():
        _logger.warning(
            "hotspot control is enabled but %s is missing, so nmcli cannot reach the host's "
            "NetworkManager; the hotspot API will report available=false. Mount it in "
            "docker-compose.yml (ADR-0007).",
            DBUS_SYSTEM_BUS_SOCKET,
        )
        return UnavailableWifiApController(
            "The host's D-Bus socket is not mounted into this container.",
            nm_state_root=Path(settings.nm_state_root),
        )
    if settings.auth_token is None and settings.hotspot_require_auth_token:
        # Not fatal, and not a refusal here — the router refuses each mutation
        # individually. Logged at startup because an operator who enabled the
        # hotspot and never set a token has a security problem they will not
        # otherwise discover until they try to use it.
        _logger.warning(
            "hotspot control is enabled but SENTRY_AUTH_TOKEN is unset; every hotspot change "
            "will be refused. Anyone joining the hotspot would otherwise reach this API "
            "without credentials."
        )
    return NmcliWifiApController(
        process_spawner=process_spawner,
        nmcli_path=settings.nmcli_path,
        connection_name=settings.hotspot_connection_name,
        nm_state_root=Path(settings.nm_state_root),
        timeout_s=settings.nmcli_timeout_s,
    )


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
    hotspot_service: HotspotService
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
    # Built before `SupervisorService` (which now takes it directly, rather
    # than the two being wired together nowhere) so live per-dongle tuning
    # actually reaches a running pair and `DeviceStatus.tuner` is populated —
    # previously constructed but never started anywhere in this file.
    control_follower = ControlFollowerService(device_registry, clock)
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
        control_follower=control_follower,
    )
    eeprom_service = EepromService(
        process_spawner=process_spawner,
        rtlsdr_library=rtlsdr_library,
        supervisor=supervisor,
        device_registry=device_registry,
        rtl_eeprom_path=settings.rtl_eeprom_path,
        event_bus=event_bus,
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
    hotspot_service = HotspotService(
        controller=_build_wifi_ap_controller(settings, process_spawner),
        event_bus=event_bus,
        clock=clock,
        default_gateway_cidr=settings.hotspot_gateway_cidr,
        confirm_timeout_s=settings.hotspot_confirm_timeout_s,
        configured_interface=settings.hotspot_interface,
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
        hotspot_service=hotspot_service,
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


RECONCILE_DEBOUNCE_S = 0.25
"""Coalesces a burst of `device_changed`/`device_removed` events into one
`reconcile()` call (finding: reconcile amplification). `reconcile()` always
reads the registry's *live* desired set rather than anything carried by the
triggering event, so a debounced call is never stale — merely less frequent —
which is what keeps an operator alternating a device between two valid ports
from holding the SDRs in continuous stop/respawn churn."""


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
    its desired set — debounced by `RECONCILE_DEBOUNCE_S` so a burst of
    events (e.g. every dongle re-arming after a container restart) triggers
    one `reconcile()` rather than one per event.

    **Guaranteed trailing reconcile (bug fix).** The previous implementation
    created one debounce task per "idle" event and, while that task was
    pending (asleep *or* already inside `reconcile()`), silently dropped
    every further event with no record that anything had been missed. A
    `device_changed` published while an in-flight `reconcile()` was still
    running past its debounce sleep — plausible with several devices to
    spawn/stop — was therefore simply lost, with no later event to ever
    re-trigger it: exactly the silent-no-op shape of a present, enabled,
    configured device that never leaves `configured` (hardware-debugging
    finding). This version instead sets a single `asyncio.Event` on every
    qualifying message and runs a single dedicated worker
    (`_reconcile_worker`) that clears the event *before* debouncing and
    reconciling, then loops back to check it again — so a `device_changed`
    that arrives at any point during the debounce sleep *or* during
    `reconcile()` itself is re-observed as "set" on the worker's next
    iteration and produces one more reconcile pass, never zero.
    """
    reconcile_requested = asyncio.Event()
    worker_task = asyncio.create_task(
        _reconcile_worker(container, reconcile_requested), name="supervisor-reconcile-worker"
    )
    subscription = container.event_bus.subscribe()
    try:
        async for message in subscription:
            if message.event not in ("device_changed", "device_removed"):
                continue
            reconcile_requested.set()
    except asyncio.CancelledError:
        raise
    except Exception:
        _logger.exception("supervisor reconcile loop crashed")
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


async def _reconcile_worker(container: AppContainer, reconcile_requested: asyncio.Event) -> None:
    """Wait for a requested reconcile, debounce, run it, and repeat while more were requested.

    Clearing `reconcile_requested` *before* debouncing/reconciling (rather
    than after) is what makes this loss-proof: any `set()` call landing
    anywhere between that `clear()` and the next `await
    reconcile_requested.wait()` is still observed, guaranteeing the run after
    the current one always happens instead of a requested reconcile being
    dropped on the floor.
    """
    while True:
        await reconcile_requested.wait()
        reconcile_requested.clear()
        try:
            await container.clock.sleep(RECONCILE_DEBOUNCE_S)
        except asyncio.CancelledError:
            return
        try:
            await container.supervisor.reconcile()
        except asyncio.CancelledError:
            return
        except Exception:
            _logger.exception("supervisor reconcile crashed")


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
            # Cancels any armed rollback timer only — deliberately does not roll
            # a hotspot back on the way out, since a container restart must not
            # tear down a working network (ADR-0007).
            await container.hotspot_service.close()
        except Exception:
            _logger.exception("error closing hotspot service")

        try:
            await container.device_registry.close()
        except Exception:
            _logger.exception("error closing device registry")

        await container.engine.dispose()


class ReferrerPolicyMiddleware:
    """Sets `Referrer-Policy: no-referrer` on every response, as raw ASGI.

    Belt-and-braces alongside the access-log redaction in
    `logging_config.py`: the SSE `?access_token=` URL should also never be
    handed to a third party via the `Referer` header a browser would
    otherwise send when navigating away from (or embedding a resource from)
    a page whose URL carries it.

    Deliberately **not** `@app.middleware("http")` (Starlette's
    `BaseHTTPMiddleware`) — that wrapper buffers/re-drives the response
    through its own `call_next` machinery and is well known to break
    long-lived `StreamingResponse`s (confirmed here: wrapping `GET
    /api/events` in it made the SSE connection never flush its first bytes
    at all). A raw ASGI middleware that only touches the `http.response.start`
    message's headers passes every other message (`http.response.body`, of
    which an SSE response emits many, one per event) straight through
    untouched.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def _send_with_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"referrer-policy", b"no-referrer"))
            await send(message)

        await self._app(scope, receive, _send_with_header)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance.

    A factory (rather than a module-level `app = FastAPI()`) so tests can
    construct a fresh app with overridden settings/dependencies without
    import-order side effects.
    """
    settings = get_settings()
    application = FastAPI(
        title="Sentry",
        description="Multi-dongle RTL-SDR controller for a Raspberry Pi.",
        version=SENTRY_VERSION,
        lifespan=_lifespan,
    )
    application.add_middleware(ReferrerPolicyMiddleware)

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
            CacheAwareSpaStaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="spa",
        )
    return application


app = create_app()
