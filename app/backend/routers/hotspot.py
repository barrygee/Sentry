"""`/api/hotspot*` — configure and run Sentry's own WiFi network (ADR-0007).

Additive to everything that already exists: a client on the LAN reaches Sentry
exactly as it did before, and a deployment that never sets
`SENTRY_HOTSPOT_CONTROL_ENABLED` is indistinguishable from one without this
router, apart from a single read-only route reporting `control_enabled: false`.

Two gates sit in front of every mutating route, and they are the whole security
posture of the feature (ADR-0007):

1. `SENTRY_HOTSPOT_CONTROL_ENABLED`, off by default, so host-network control is
   opt-in at deploy time by someone with shell access to the Pi.
2. `SENTRY_AUTH_TOKEN` must be set, because raising an access point puts anyone
   in radio range holding the passphrase on the same segment as an API that
   spawns processes and writes dongle firmware.

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
    get_hotspot_service,
    get_settings_dependency,
)
from app.backend.interfaces.clock import Clock
from app.backend.schemas.errors import error_detail
from app.backend.schemas.hotspot import (
    HotspotActivationRequest,
    HotspotClientItem,
    HotspotClientsResponse,
    HotspotConfigRequest,
    HotspotControlRequest,
    HotspotControlResponse,
    HotspotErrorSummary,
    HotspotStateResponse,
    HotspotWarning,
    WirelessInterfaceItem,
    WirelessInterfacesResponse,
)
from app.backend.security import require_console_session
from app.backend.services.console_auth import ConsoleAuthService
from app.backend.services.host_control_settings import HostControlSettingsService
from app.backend.services.hotspot import HotspotError, HotspotService, HotspotSnapshot

router = APIRouter(
    prefix="/hotspot", tags=["hotspot"], dependencies=[Depends(require_console_session)]
)

_STATUS_BY_ERROR_CODE: dict[str, int] = {
    "hotspot_control_disabled": status.HTTP_403_FORBIDDEN,
    "auth_token_required": status.HTTP_409_CONFLICT,
    "hotspot_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "passphrase_required": status.HTTP_409_CONFLICT,
    "hotspot_not_configured": status.HTTP_409_CONFLICT,
    "uplink_loss_unconfirmed": status.HTTP_409_CONFLICT,
    "no_wireless_interface": status.HTTP_409_CONFLICT,
    "interface_not_found": status.HTTP_409_CONFLICT,
    "interface_ap_unsupported": status.HTTP_409_CONFLICT,
    "hotspot_busy": status.HTTP_409_CONFLICT,
    "no_pending_confirmation": status.HTTP_409_CONFLICT,
    "hotspot_command_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "hotspot_command_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
}
"""Every code the service can raise, mapped to its status. A code absent from
this table is a bug rather than a 500-by-default, so `_as_http_exception`
falls back loudly to 500 and the table is the single place to look."""


def _as_http_exception(error: HotspotError) -> HTTPException:
    """Translate a service error into the uniform `{"detail": {...}}` envelope."""
    return HTTPException(
        status_code=_STATUS_BY_ERROR_CODE.get(error.code, status.HTTP_500_INTERNAL_SERVER_ERROR),
        detail=error_detail(error.code, error.message, **error.context),
    )


def _require_control_enabled(control_enabled: bool) -> None:
    """Refuse a mutating call unless host-network control is switched on.

    `control_enabled` is the *effective* value — the stored switch, or `.env`
    forcing it on (ADR-0013). The message no longer names an environment
    variable, because the console can now turn this on itself.
    """
    if not control_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                "hotspot_control_disabled",
                "Hotspot control is switched off for this Sentry. Turn it on in "
                "Settings, then try again.",
            ),
        )


def _require_console_password(settings: Settings, password_set: bool) -> None:
    """Refuse a mutating call while the console has no password.

    A hard refusal rather than a warning: the hotspot is the one feature that
    invites unknown machines onto the same network as this API, so shipping it
    unauthenticated is not a trade-off an operator should be able to make by
    omission.

    The rule is unchanged from when this checked `SENTRY_AUTH_TOKEN`; only what
    "authenticated" means has moved (ADR-0010). `SENTRY_HOTSPOT_REQUIRE_AUTH_TOKEN`
    keeps its name so an existing `.env` is not silently ignored — a rename would
    turn a deliberate `false` into an accidental `true`, quietly re-imposing a
    gate an operator had switched off.
    """
    if settings.hotspot_require_auth_token and not password_set:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "console_password_required",
                "Set a console password before starting a hotspot: anyone who joins the "
                "network can otherwise reach this API without signing in.",
            ),
        )


def _guard_mutation(control_enabled: bool, settings: Settings, password_set: bool) -> None:
    """Apply both gates, in the order an operator should fix them."""
    _require_control_enabled(control_enabled)
    _require_console_password(settings, password_set)


def _build_warnings(
    snapshot: HotspotSnapshot, settings: Settings, password_set: bool
) -> tuple[HotspotWarning, ...]:
    """Collect the non-fatal conditions worth telling an operator about.

    Warnings never block a read — they are how the API says "this will not do
    what you expect" without pretending to know better than the operator.
    """
    warnings: list[HotspotWarning] = []
    if not snapshot.available:
        warnings.append("nm_unavailable")
    if settings.hotspot_require_auth_token and not password_set:
        warnings.append("auth_token_missing")
    if snapshot.uplink_interface_is_hotspot_interface:
        warnings.append("single_radio_uplink_loss")
    # SENTRY_ADVERTISED_HOST is never overridden here — an operator who set it
    # did so for a reason (NAT, a proxy) that the hotspot must not silently
    # second-guess. It is reported so the UI can explain why a joined client is
    # being handed an address it cannot reach.
    gateway_address = settings.hotspot_gateway_address()
    if snapshot.state.profile_exists and settings.advertised_host not in (None, gateway_address):
        warnings.append("advertised_host_overrides_gateway")
    return tuple(warnings)


def _to_state_response(
    snapshot: HotspotSnapshot,
    settings: Settings,
    generated_at: int,
    password_set: bool,
    control_enabled: bool,
) -> HotspotStateResponse:
    """Map the service's snapshot onto the wire shape.

    The passphrase has no representation here at all — only `passphrase_set`.
    There is no code path in this module that could return it, which is the
    point (ADR-0007).
    """
    state = snapshot.state
    gateway_address: str | None = None
    if state.gateway_cidr:
        gateway_address = state.gateway_cidr.split("/", 1)[0]

    last_error = None
    if snapshot.last_error is not None:
        code, message, timestamp_ms, stderr_tail = snapshot.last_error
        last_error = HotspotErrorSummary(
            code=code, message=message, ts=timestamp_ms, stderr_tail=stderr_tail
        )

    return HotspotStateResponse(
        available=snapshot.available,
        control_enabled=control_enabled,
        auth_token_configured=password_set,
        configured=state.profile_exists,
        enabled=state.autoconnect,
        active=state.active,
        interface=state.interface,
        ssid=state.ssid,
        hidden=state.hidden,
        security=state.security,
        band=state.band,
        channel=state.channel,
        gateway_address=gateway_address,
        gateway_cidr=state.gateway_cidr,
        passphrase_set=state.passphrase_set,
        uplink_interface_is_hotspot_interface=snapshot.uplink_interface_is_hotspot_interface,
        pending_confirmation=snapshot.pending_confirmation,
        confirm_deadline_ms=snapshot.confirm_deadline_ms,
        last_error=last_error,
        warnings=_build_warnings(snapshot, settings, password_set),
        generated_at=generated_at,
    )


@router.get(
    "",
    response_model=HotspotStateResponse,
    status_code=status.HTTP_200_OK,
    summary="The hotspot's current configuration and state",
)
async def get_hotspot(
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> HotspotStateResponse:
    """Describe the hotspot, degrading rather than failing.

    Always 200. A host with no NetworkManager answers `available: false` and a
    `nm_unavailable` warning — a client can therefore always render something
    truthful instead of an error it cannot explain.
    """
    snapshot = await hotspot_service.get_snapshot()
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.get(
    "/interfaces",
    response_model=WirelessInterfacesResponse,
    status_code=status.HTTP_200_OK,
    summary="Wireless interfaces the hotspot could use",
)
async def list_interfaces(
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    clock: Clock = Depends(get_clock),
) -> WirelessInterfacesResponse:
    """List candidate interfaces, flagging which one carries the host's own link."""
    interfaces = await hotspot_service.list_interfaces()
    return WirelessInterfacesResponse(
        interfaces=tuple(
            WirelessInterfaceItem(
                name=entry.name,
                mac_address=entry.mac_address,
                supports_ap=entry.supports_ap,
                state=entry.state,
                station_ssid=entry.station_ssid,
                ipv4_addresses=entry.ipv4_addresses,
                carries_default_route=entry.carries_default_route,
                in_use_by=entry.active_connection_name,
            )
            for entry in interfaces
        ),
        generated_at=clock.now_ms(),
    )


@router.get(
    "/clients",
    response_model=HotspotClientsResponse,
    status_code=status.HTTP_200_OK,
    summary="DHCP leases the hotspot has issued",
)
async def list_clients(
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    clock: Clock = Depends(get_clock),
) -> HotspotClientsResponse:
    """Return the hotspot's leases, or `null` when they cannot be read.

    `null` and `[]` are different answers and must stay so: one means "this host
    cannot tell you", the other means "nothing is connected". Collapsing them
    would have the UI confidently report an empty network on a machine that
    simply has no lease file.
    """
    now_ms = clock.now_ms()
    clients = hotspot_service.list_clients()
    if clients is None:
        return HotspotClientsResponse(clients=None, generated_at=now_ms)
    return HotspotClientsResponse(
        clients=tuple(
            HotspotClientItem(
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
    response_model=HotspotStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace the hotspot configuration",
)
async def put_hotspot(
    request_body: HotspotConfigRequest,
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> HotspotStateResponse:
    """Write the whole configuration, then bring the hotspot up or down to match.

    Omitting `passphrase` keeps the stored one — the mechanism that lets an
    operator rename the network without the server ever handling the secret
    again (WCAG 3.3.7 as much as security: not re-asking for something
    unchanged is a requirement, not a courtesy).
    """
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await hotspot_service.apply_configuration(
            ssid=request_body.ssid,
            passphrase=(
                request_body.passphrase.get_secret_value()
                if request_body.passphrase is not None
                else None
            ),
            security=request_body.security,
            hidden=request_body.hidden,
            enabled=request_body.enabled,
            interface=request_body.interface,
            band=request_body.band,
            channel=request_body.channel,
            gateway_cidr=request_body.gateway_cidr,
            confirm_uplink_loss=request_body.confirm_uplink_loss,
        )
    except HotspotError as error:
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
    response_model=HotspotStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Start the configured hotspot",
)
async def enable_hotspot(
    request_body: HotspotActivationRequest,
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> HotspotStateResponse:
    """Bring the hotspot up provisionally; it rolls back unless confirmed.

    Separate from `PUT` so the UI's on/off switch never resends the whole
    configuration, and therefore never has to be holding the passphrase just to
    flip a switch.
    """
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await hotspot_service.enable(request_body.confirm_uplink_loss)
    except HotspotError as error:
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
    response_model=HotspotStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop the hotspot",
)
async def disable_hotspot(
    request_body: HotspotActivationRequest,
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> HotspotStateResponse:
    """Bring the hotspot down and stop it starting on boot."""
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await hotspot_service.disable(request_body.confirm_uplink_loss)
    except HotspotError as error:
        raise _as_http_exception(error) from error
    return _to_state_response(
        snapshot,
        settings,
        clock.now_ms(),
        await console_auth.is_password_set(),
        await host_control.hotspot_control_enabled(),
    )


@router.post(
    "/confirm",
    response_model=HotspotStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Keep the hotspot that is awaiting confirmation",
)
async def confirm_hotspot(
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
    clock: Clock = Depends(get_clock),
) -> HotspotStateResponse:
    """Cancel the pending rollback and let the hotspot survive a reboot.

    Reaching this route at all is the proof the commit-confirm flow wants: the
    API is still answering with the hotspot running.
    """
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        snapshot = await hotspot_service.confirm()
    except HotspotError as error:
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
    summary="Delete the hotspot configuration",
)
async def delete_hotspot(
    hotspot_service: HotspotService = Depends(get_hotspot_service),
    settings: Settings = Depends(get_settings_dependency),
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
) -> Response:
    """Forget the network entirely, including its stored password."""
    _guard_mutation(
        await host_control.hotspot_control_enabled(),
        settings,
        await console_auth.is_password_set(),
    )
    try:
        await hotspot_service.forget()
    except HotspotError as error:
        raise _as_http_exception(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/control",
    response_model=HotspotControlResponse,
    status_code=status.HTTP_200_OK,
    summary="Switch this Sentry's hotspot control on or off",
)
async def set_hotspot_control(
    request_body: HotspotControlRequest,
    console_auth: ConsoleAuthService = Depends(get_console_auth_service),
    host_control: HostControlSettingsService = Depends(get_host_control_settings),
) -> HotspotControlResponse:
    """Turn host-network control on or off without a restart (ADR-0013).

    This is the one route that can *grant* the capability every other route in
    this module guards, so it carries its own gate: a console with no password
    is refused outright, not merely warned. ADR-0007 made shell access the thing
    standing between a stranger and this host's networking; moving the switch
    into the UI replaces that with the console password, which therefore has to
    exist before the switch will move at all.

    Deliberately not guarded by `_require_control_enabled` — that would make the
    switch require itself.
    """
    if not await console_auth.is_password_set():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "console_password_required",
                "Set a Sentry controller password before switching hotspot control on: "
                "it is what stops anyone who can reach this console reconfiguring the "
                "Pi's networking.",
            ),
        )

    await host_control.set_hotspot_control_enabled(request_body.enabled)
    return HotspotControlResponse(
        control_enabled=await host_control.hotspot_control_enabled(),
        forced_by_environment=host_control.hotspot_control_is_forced,
    )
