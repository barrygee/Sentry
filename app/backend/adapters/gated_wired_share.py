"""A `WiredShareController` that consults the host-control switch before every call.

The wired counterpart of `GatedWifiApController`, and it exists for the same
reason and shares its switch: `host_control_settings.hotspot_control_enabled` is
named for the hotspot but means "the API may reconfigure this host's
networking", and sharing an Ethernet port is exactly that capability (ADR-0014).
A second switch would ask an operator to grant the same permission twice, and
would let them grant half of it — which is not a distinction the risk actually
has, since either one can take the Pi off the network.

Delegation rather than a flag inside `NmcliWiredShareController`, so ADR-0007's
central property survives here too: with control switched off, *nothing* reaches
nmcli or the D-Bus socket — the disabled controller answers instead, and the
real one is never asked.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.backend.interfaces.types import (
    HotspotClient,
    WiredInterface,
    WiredShareProfile,
    WiredShareRuntimeState,
)
from app.backend.interfaces.wired_share import WiredShareController


class GatedWiredShareController:
    """Routes every call to `enabled_controller` or `disabled_controller`.

    The predicate is awaited on each call rather than cached: it reads a single
    row from a local SQLite file, and staleness here would mean sharing switched
    off in the UI still answering as though it were on.
    """

    def __init__(
        self,
        *,
        enabled_controller: WiredShareController,
        disabled_controller: WiredShareController,
        control_enabled: Callable[[], Awaitable[bool]],
    ) -> None:
        self._enabled_controller = enabled_controller
        self._disabled_controller = disabled_controller
        self._control_enabled = control_enabled

    async def _controller(self) -> WiredShareController:
        if await self._control_enabled():
            return self._enabled_controller
        return self._disabled_controller

    async def is_available(self) -> bool:
        controller = await self._controller()
        return await controller.is_available()

    async def list_wired_interfaces(self) -> tuple[WiredInterface, ...]:
        controller = await self._controller()
        return await controller.list_wired_interfaces()

    async def read_state(self) -> WiredShareRuntimeState:
        controller = await self._controller()
        return await controller.read_state()

    async def apply_profile(self, profile: WiredShareProfile) -> None:
        controller = await self._controller()
        await controller.apply_profile(profile)

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

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        """Synchronous, so it cannot await the switch.

        Delegates to the enabled controller unconditionally, which is safe
        precisely because it is the one method that touches no network stack:
        it reads NetworkManager's dnsmasq lease file. With sharing off there are
        no leases and the answer is empty or `None` either way.
        """
        return self._enabled_controller.list_clients(interface)
