"""`/api/wired*` — share one of the Pi's Ethernet ports with a directly-cabled machine (ADR-0014).

Additive to everything that already exists: a client on the LAN reaches Sentry
exactly as it did before, and a deployment that never switches host-network
control on is indistinguishable from one without this router, apart from a
single read-only route reporting `control_enabled: false`.

The same two gates the hotspot uses sit in front of every mutating route here,
and for the same reasons:

1. **Host-network control must be switched on.** This is literally the hotspot's
   switch, not a parallel one — it means "the API may reconfigure this host's
   networking", which is exactly the permission this router needs.
2. **A console password must be set**, because a shared Ethernet port puts
   whoever plugs a cable in on the same segment as an API that spawns processes
   and writes dongle firmware.

`GET` is deliberately exempt from both — a read has to work in order to *tell*
an operator that the gates are why nothing else does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.backend.config import Settings
from app.backend.dependencies import (
    get_clock,
    get_console_auth_service,
    get_host_control_settings,
    get_settings_dependency,
    get_wired_share_service,
)
from app.backend.interfaces.clock import Clock
from app.backend.schemas.errors import error_detail
from app.backend.schemas.wired_share import (
    WiredClientItem,
    WiredClientsResponse,
    WiredInterfaceItem,
    WiredInterfacesResponse,
    WiredShareActivationRequest,
    WiredShareConfigRequest,
    WiredShareErrorSummary,
    WiredShareStateResponse,
    WiredShareWarning,
)
from app.backend.security import require_console_session
from app.backend.services.console_auth import ConsoleAuthService
from app.backend.services.host_control_settings import HostControlSettingsService
from app.backend.services.wired_share import WiredError, WiredShareService, WiredShareSnapshot

router = APIRouter(prefix="/wired", tags=["wired"], dependencies=[Depends(require_console_session)])

_STATUS_BY_ERROR_CODE: dict[str, int] = {
    "wired_control_disabled": status.HTTP_403_FORBIDDEN,
    "console_password_required": status.HTTP_409_CONFLICT,
    "wired_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "wired_not_configured": status.HTTP_409_CONFLICT,
    "uplink_loss_unconfirmed": status.HTTP_409_CONFLICT,
    "no_wired_interface": status.HTTP_409_CONFLICT,
    "interface_not_found": status.HTTP_409_CONFLICT,
    "wired_busy": status.HTTP_409_CONFLICT,
    "wired_not_running": status.HTTP_409_CONFLICT,
    "lease_not_found": status.HTTP_404_NOT_FOUND,
    "leases_unreadable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "no_pending_confirmation": status.HTTP_409_CONFLICT,
    "wired_command_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "wired_command_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
}
"""Every code the service can raise, mapped to its status. A code absent from
this table is a bug rather than a 500-by-default, so `_as_http_exception` falls
back loudly to 500 and the table is the single place to look."""


def _as_http_exception(error: WiredError) -> HTTPException:
    """Translate a service error into the uniform `{"detail": {...}}` envelope."""
    return HTTPException(
        status_code=_STATUS_BY_ERROR_CODE.get(error.code, status.HTTP_500_INTERNAL_SERVER_ERROR),
        detail=error_detail(error.code, error.message, **error.context),
    )


def _require_control_enabled(control_enabled: bool) -> None:
    """Refuse a mutating call unless host-network control is switched on."""
    if not control_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                "wired_control_disabled",
                "Host network control is switched off for this Sentry. Turn it on in "
                "Settings, then try again.",
            ),
        )


def _require_console_password(settings: Settings, password_set: bool) -> None:
    """Refuse a mutating call while the console has no password.

    A hard refusal rather than a warning, on the same reasoning the hotspot
    applies: sharing a port invites an unknown machine onto the same network as
    this API, and shipping that unauthenticated is not a trade-off an operator
    should be able to make by omission.

    Reuses `SENTRY_HOTSPOT_REQUIRE_AUTH_TOKEN` rather than adding a second
    variable. An operator who deliberately switched that gate off did so for
    their whole Sentry, not for one transport, and a second name would silently
    re-impose the gate they had removed.
    """
    if settings.hotspot_require_auth_token and not password_set:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "console_password_required",
                "Set a console password before sharing an Ethernet port: anyone who plugs "
                "in a cable can otherwise reach this API without signing in.",
            ),
        )


def _guard_mutation(control_enabled: bool, settings: Settings, password_set: bool) -> None:
    """Apply both gates, in the order an operator should fix them."""
    _require_control_enabled(control_enabled)
    _require_console_password(settings, password_set)


def _build_warnings(
    snapshot: WiredShareSnapshot, settings: Settings, password_set: bool
) -> tuple[WiredShareWarning, ...]:
    """Collect the non-fatal conditions worth telling an operator about.

    Warnings never block a read — they are how the API says "this will not do
    what you expect" without pretending to know better than the operator.
    """
    warnings: list[WiredShareWarning] = []
    if not snapshot.available:
        warnings.append("nm_unavailable")
    if settings.hotspot_require_auth_token and not password_set:
        warnings.append("console_password_missing")
    if snapshot.uplink_interface_is_share_interface:
        warnings.append("shares_uplink_port")
    # Only meaningful once sharing is actually up: an unplugged port on a share
    # nobody has started yet is the expected state, not a problem to report.
    if snapshot.state.active and snapshot.carrier_up is False:
        warnings.append("no_carrier")
    # SENTRY_ADVERTISED_HOST is never overridden here — an operator who set it
    # did so for a reason (NAT, a proxy) that this must not silently
    # second-guess. It is reported so the UI can explain why a cabled machine is
    # being handed an address it cannot reach.
    gateway_address = settings.wired_gateway_address()
    if snapshot.state.profile_exists and settings.advertised_host not in (None, gateway_address):
        warnings.append("advertised_host_overrides_gateway")
    return tuple(warnings)


def _to_state_response(
    snapshot: WiredShareSnapshot,
    settings: Settings,
    generated_at: int,
    password_set: bool,
    control_enabled: bool,
) -> WiredShareStateResponse:
    """Map the service's snapshot onto the wire shape."""
    state = snapshot.state
    gateway_address: str | None = None
    if state.gateway_cidr:
        gateway_address = state.gateway_cidr.split("/", 1)[0]

    last_error = None
    if snapshot.last_error is not None:
        code, message, timestamp_ms, stderr_tail = snapshot.last_error
        last_error = WiredShareErrorSummary(
            code=code, message=message, ts=timestamp_ms, stderr_tail=stderr_tail
        )

    return WiredShareStateResponse(
        available=snapshot.available,
        control_enabled=control_enabled,
        console_password_set=password_set,
        configured=state.profile_exists,
        enabled=state.autoconnect,
        active=state.active,
        interface=state.interface,
        gateway_address=gateway_address,
        gateway_cidr=state.gateway_cidr,
        carrier_up=snapshot.carrier_up,
        uplink_interface_is_share_interface=snapshot.uplink_interface_is_share_interface,
        pending_confirmation=snapshot.pending_confirmation,
        confirm_deadline_ms=snapshot.confirm_deadline_ms,
        last_error=last_error,
        warnings=_build_warnings(snapshot, settings, password_set),
        generated_at=generated_at,
    )


@router.get(
    "",
    response_model=WiredShareStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Wired sharing's current configuration and state",
)
async def get_wired(
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> WiredShareStateResponse:
    """Describe wired sharing, degrading rather than failing.

    Always 200. A host with no NetworkManager answers `available: false` and a
    `nm_unavailable` warning — a client can therefore always render something
    truthful instead of an error it cannot explain.
    """
    snapshot = await wired_service.get_snapshot()
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.get(
    "/interfaces",
    response_model=WiredInterfacesResponse,
    status_code=status.HTTP_200_OK,
    summary="Ethernet ports that could be shared",
)
async def list_wired_interfaces(
    wired_service: WiredShareService = Depends(get_wired_share_service),
    clock: Clock = Depends(get_clock),
) -> WiredInterfacesResponse:
    """List candidate ports, flagging which one carries the host's own link."""
    interfaces = await wired_service.list_interfaces()
    return WiredInterfacesResponse(
        interfaces=tuple(
            WiredInterfaceItem(
                name=entry.name,
                mac_address=entry.mac_address,
                state=entry.state,
                ipv4_addresses=entry.ipv4_addresses,
                carries_default_route=entry.carries_default_route,
                carrier_up=entry.carrier_up,
                # Our own share does not count as something else using the port.
                # NetworkManager reports the share's profile as the active
                # connection while it is up, and the console reads a non-null
                # `in_use_by` as "sharing here will cut a link" — which would
                # show that warning *because* sharing had started.
                in_use_by=(
                    None
                    if entry.active_connection_name == wired_service.wired_connection_name
                    else entry.active_connection_name
                ),
            )
            for entry in interfaces
        ),
        generated_at=clock.now_ms(),
    )


@router.get(
    "/clients",
    response_model=WiredClientsResponse,
    status_code=status.HTTP_200_OK,
    summary="DHCP leases the wired share has issued",
)
async def list_wired_clients(
    wired_service: WiredShareService = Depends(get_wired_share_service),
    clock: Clock = Depends(get_clock),
) -> WiredClientsResponse:
    """Return the share's leases, or `null` when they cannot be read.

    `null` and `[]` are different answers and must stay so: one means "this host
    cannot tell you", the other means "nothing is cabled in". Collapsing them
    would have the UI confidently report an empty network on a machine that
    simply has no lease file.
    """
    now_ms = clock.now_ms()
    clients = await wired_service.list_clients()
    if clients is None:
        return WiredClientsResponse(clients=None, generated_at=now_ms)
    return WiredClientsResponse(
        clients=tuple(
            WiredClientItem(
                mac_address=entry.mac_address,
                ip_address=entry.ip_address,
                hostname=entry.hostname,
                lease_expires_at_ms=entry.lease_expires_at_ms,
                expired=entry.lease_expires_at_ms < now_ms,
            )
            for entry in clients
        ),
        generated_at=now_ms,
    )


@router.put(
    "",
    response_model=WiredShareStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace the wired-sharing configuration",
)
async def put_wired(
    request_body: WiredShareConfigRequest,
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> WiredShareStateResponse:
    """Write the whole configuration, then bring sharing up or down to match."""
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await wired_service.apply_configuration(
            enabled=request_body.enabled,
            interface=request_body.interface,
            gateway_cidr=request_body.gateway_cidr,
            confirm_uplink_loss=request_body.confirm_uplink_loss,
        )
    except WiredError as error:
        # Covers every subclass — busy, unavailable, unconfirmed uplink loss —
        # since each carries its own `code`, and the code is what decides the
        # status. Catching them individually would only duplicate this line.
        raise _as_http_exception(error) from error
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.post(
    "/enable",
    response_model=WiredShareStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Start the configured wired share",
)
async def enable_wired(
    request_body: WiredShareActivationRequest,
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> WiredShareStateResponse:
    """Bring the share up provisionally; it rolls back unless confirmed.

    Separate from `PUT` so the UI's on/off switch never resends the whole
    configuration.
    """
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await wired_service.enable(request_body.confirm_uplink_loss)
    except WiredError as error:
        raise _as_http_exception(error) from error
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.post(
    "/disable",
    response_model=WiredShareStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop the wired share",
)
async def disable_wired(
    request_body: WiredShareActivationRequest,
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> WiredShareStateResponse:
    """Bring the share down and stop it starting on boot."""
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await wired_service.disable(request_body.confirm_uplink_loss)
    except WiredError as error:
        raise _as_http_exception(error) from error
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.delete(
    "/clients/{mac_address}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Release one DHCP lease",
)
async def release_wired_lease(
    mac_address: str,
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
) -> None:
    """Ask the share's DHCP server to forget one lease.

    Keyed by MAC alone: the address to release is looked up from the lease list,
    so a request cannot pair one machine's MAC with another's IP.

    This frees a reservation; it does not unplug anything. A machine still
    cabled in will ask again and may be handed the same address back.
    """
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        await wired_service.release_lease(mac_address)
    except WiredError as error:
        raise _as_http_exception(error) from error


@router.post(
    "/confirm",
    response_model=WiredShareStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Keep the wired share that is awaiting confirmation",
)
async def confirm_wired(
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> WiredShareStateResponse:
    """Cancel the pending rollback and let the share survive a reboot.

    Reaching this route at all is the proof the commit-confirm flow wants: the
    API is still answering with the Pi's uplink port serving DHCP instead.
    """
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await wired_service.confirm()
    except WiredError as error:
        raise _as_http_exception(error) from error
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the wired-sharing configuration",
)
async def delete_wired(
    wired_service: WiredShareService = Depends(get_wired_share_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
) -> Response:
    """Forget the wired-sharing profile entirely."""
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        await wired_service.forget()
    except WiredError as error:
        raise _as_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
