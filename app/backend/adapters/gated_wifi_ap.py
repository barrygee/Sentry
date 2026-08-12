"""A `WifiApController` that consults a switch before every call (ADR-0013).

Hotspot control used to be selected once, at startup: `.env` said yes and the
real nmcli controller was built, or it said no and a null object took its place.
Making the switch operator-flippable means the choice has to be made per call
instead, because the answer can now change while the process runs.

Delegation rather than a flag inside `NmcliWifiApController`, so that ADR-0007's
central property survives intact: with control switched off, *nothing* here
reaches nmcli or the D-Bus socket — the disabled controller answers instead, and
the real one is never asked. A boolean checked inside the real adapter would
have put the enforcement one layer deeper than the capability, which is the
wrong way round.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.backend.interfaces.types import (
    HotspotClient,
    HotspotProfile,
    HotspotRuntimeState,
    WirelessInterface,
)
from app.backend.interfaces.wifi_ap import WifiApController


class GatedWifiApController:
    """Routes every call to `enabled_controller` or `disabled_controller`.

    The predicate is awaited on each call rather than cached: it reads a single
    row from a local SQLite file, and staleness here would mean a hotspot
    switched off in the UI still answering as though it were on.
    """

    def __init__(
        self,
        *,
        enabled_controller: WifiApController,
        disabled_controller: WifiApController,
        control_enabled: Callable[[], Awaitable[bool]],
    ) -> None:
        self._enabled_controller = enabled_controller
        self._disabled_controller = disabled_controller
        self._control_enabled = control_enabled

    async def _controller(self) -> WifiApController:
        if await self._control_enabled():
            return self._enabled_controller
        return self._disabled_controller

    async def is_available(self) -> bool:
        controller = await self._controller()
        return await controller.is_available()

    async def list_wireless_interfaces(self) -> tuple[WirelessInterface, ...]:
        controller = await self._controller()
        return await controller.list_wireless_interfaces()

    async def read_state(self) -> HotspotRuntimeState:
        controller = await self._controller()
        return await controller.read_state()

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        controller = await self._controller()
        await controller.apply_profile(profile, passphrase)

    async def activate(self) -> None:
        controller = await self._controller()
        await controller.activate()

    async def deactivate(self) -> None:
        controller = await self._controller()
        await controller.deactivate()

    async def set_autoconnect(self, autoconnect: bool) -> None:
        controller = await self._controller()
        await controller.set_autoconnect(autoconnect)

    async def delete_profile(self) -> None:
        controller = await self._controller()
        await controller.delete_profile()

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        controller = await self._controller()
        await controller.release_lease(interface, ip_address, mac_address)

    async def active_connection_on(self, interface: str) -> str | None:
        controller = await self._controller()
        return await controller.active_connection_on(interface)

    async def activate_named(self, connection_name: str) -> None:
        controller = await self._controller()
        await controller.activate_named(connection_name)

    def list_clients(self) -> tuple[HotspotClient, ...] | None:
        """Synchronous, so it cannot await the switch.

        Delegates to the enabled controller unconditionally, which is safe
        precisely because it is the one method that touches no network stack:
        it reads NetworkManager's dnsmasq lease file. With the hotspot off there
        are no leases and the answer is empty or `None` either way.
        """
        return self._enabled_controller.list_clients()
