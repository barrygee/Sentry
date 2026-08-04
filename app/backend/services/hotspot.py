"""Access-point lifecycle: configure, raise, roll back (ADR-0007).

Touches no OS primitive of its own — no `Path`, no `subprocess`, no socket.
Everything hardware-facing goes through the injected `WifiApController`, which
is what makes the two genuinely interesting behaviours here — the refusal to
silently drop the host's own uplink, and the commit-confirm rollback timer —
testable on a laptop with no radio.

**Why a rollback timer exists at all.** On a single-radio Pi, raising an access
point on the interface that carries the uplink necessarily tears that
connection down. If the new network then fails to come up — a channel the
regulatory domain forbids, a driver that will not do AP mode, SAE the chip does
not support — the host is left with neither, and recovering means physically
attaching a keyboard. So an activation is provisional: it reverts itself unless
someone calls `confirm()` from the other side, proving the API is still
reachable. This is the pattern network gear has used for decades, and it is the
only mechanism that actually prevents that lockout rather than warning about it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass
from typing import Any

from app.backend.interfaces.clock import Clock
from app.backend.interfaces.types import (
    HotspotBand,
    HotspotClient,
    HotspotProfile,
    HotspotRuntimeState,
    HotspotSecurity,
    WirelessInterface,
)
from app.backend.interfaces.wifi_ap import (
    WifiApCommandError,
    WifiApController,
    WifiApTimeoutError,
    WifiApUnavailableError,
)
from app.backend.schemas.events import NoticeItem
from app.backend.services.event_bus import EventBus, SseMessage

_logger = logging.getLogger(__name__)


class HotspotError(Exception):
    """A hotspot operation the router should translate into an error response.

    Carries the machine-readable `code` and any context the operator needs, so
    the router maps it to the uniform `{"detail": {...}}` envelope without
    re-deriving anything.
    """

    def __init__(self, code: str, message: str, **context: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


class HotspotBusyError(HotspotError):
    """Another hotspot operation is already running."""

    def __init__(self) -> None:
        super().__init__(
            "hotspot_busy",
            "Another hotspot change is in progress. Wait for it to finish and try again.",
        )


class HotspotUnavailableError(HotspotError):
    """This host cannot control an access point at all."""

    def __init__(self, reason: str) -> None:
        super().__init__("hotspot_unavailable", reason)


class UplinkLossUnconfirmedError(HotspotError):
    """The operation would drop a connection currently in use, and nobody said it could."""


@dataclass(frozen=True, slots=True)
class HotspotSnapshot:
    """Everything the API layer needs to describe the hotspot in one response.

    Assembled here rather than in the router so the "what is true right now"
    question has exactly one answer, shared by `GET /api/hotspot` and by every
    mutator's success body.
    """

    available: bool
    state: HotspotRuntimeState
    uplink_interface_is_hotspot_interface: bool
    pending_confirmation: bool
    confirm_deadline_ms: int | None
    last_error: tuple[str, str, int] | None
    """`(code, message, ts)` of the last failure, or None."""


class HotspotService:
    """Owns Sentry's single access-point profile and its provisional activations."""

    def __init__(
        self,
        controller: WifiApController,
        event_bus: EventBus,
        clock: Clock,
        default_gateway_cidr: str,
        confirm_timeout_s: float,
        configured_interface: str | None,
    ) -> None:
        self._controller = controller
        self._event_bus = event_bus
        self._clock = clock
        self._default_gateway_cidr = default_gateway_cidr
        self._confirm_timeout_s = confirm_timeout_s
        self._configured_interface = configured_interface

        self._lock = asyncio.Lock()
        """Serialises every mutation across the whole process.

        Held for the duration of a change, and probed rather than awaited by
        callers — a queue of pending `nmcli` invocations behind a wedged one is
        strictly worse than a fast `409`. Sentry is a single process by
        construction (ADR-0001), so an in-process lock is a complete fix here
        rather than a mitigation.
        """

        self._rollback_task: asyncio.Task[None] | None = None
        self._confirm_deadline_ms: int | None = None
        self._rollback_target: str | None = None
        self._last_error: tuple[str, str, int] | None = None
        self._live_passphrase: str | None = None
        """The passphrase of the change currently in flight, held only so failure
        output can be scrubbed of it. Cleared the moment the change finishes."""

    # ------------------------------------------------------------------ reads

    async def get_snapshot(self) -> HotspotSnapshot:
        """Describe the hotspot as it is right now.

        Never raises. A host that cannot do any of this answers with
        `available=False` and an absent profile, which is what lets
        `GET /api/hotspot` stay a 200 instead of failing.
        """
        available = await self._controller.is_available()
        state = await self._controller.read_state()
        uplink_collision = False
        if state.interface:
            uplink_collision = await self._interface_is_carrying_uplink(state.interface)
        return HotspotSnapshot(
            available=available,
            state=state,
            uplink_interface_is_hotspot_interface=uplink_collision,
            pending_confirmation=self._rollback_task is not None,
            confirm_deadline_ms=self._confirm_deadline_ms,
            last_error=self._last_error,
        )

    async def list_interfaces(self) -> tuple[WirelessInterface, ...]:
        """List wireless interfaces the operator could put the hotspot on."""
        return await self._controller.list_wireless_interfaces()

    def list_clients(self) -> tuple[HotspotClient, ...] | None:
        """List the hotspot's DHCP leases. `None` means unknown, never zero."""
        return self._controller.list_clients()

    @property
    def default_gateway_cidr(self) -> str:
        """The AP-side address used when a request does not name one."""
        return self._default_gateway_cidr

    # -------------------------------------------------------------- mutations

    async def apply_configuration(
        self,
        *,
        ssid: str,
        passphrase: str | None,
        security: HotspotSecurity,
        hidden: bool,
        enabled: bool,
        interface: str | None,
        band: HotspotBand,
        channel: int,
        gateway_cidr: str | None,
        confirm_uplink_loss: bool,
    ) -> HotspotSnapshot:
        """Write the profile, then bring it up or down to match `enabled`.

        `passphrase=None` means leave the stored key alone — the mechanism that
        keeps the secret write-only. A brand-new profile has no stored key, so
        that case is refused rather than producing an open network.
        """
        async with self._exclusive():
            await self._require_available()
            existing = await self._controller.read_state()
            if passphrase is None and not existing.passphrase_set:
                raise HotspotError(
                    "passphrase_required",
                    "Set a password for the hotspot before enabling it.",
                    reason="no_stored_passphrase",
                )
            if passphrase is None and security != existing.security:
                # Changing the key-management scheme rewrites the security
                # settings wholesale; carrying an unseen key across that is not
                # something this can promise, so ask for it explicitly.
                raise HotspotError(
                    "passphrase_required",
                    "Re-enter the password when changing the security type.",
                    reason="security_changed",
                )

            chosen_interface = await self._choose_interface(interface, confirm_uplink_loss)
            profile = HotspotProfile(
                ssid=ssid,
                hidden=hidden,
                security=security,
                band=band,
                channel=channel,
                gateway_cidr=gateway_cidr or self._default_gateway_cidr,
                interface=chosen_interface,
                # Never set on a write. Persistence across reboot is earned by
                # confirming the activation, not by asking for it.
                autoconnect=False,
            )

            self._live_passphrase = passphrase
            try:
                await self._guard(self._controller.apply_profile(profile, passphrase))
                if enabled:
                    await self._activate_provisionally(chosen_interface)
                else:
                    await self._cancel_rollback()
                    await self._guard(self._controller.deactivate())
                    await self._guard(self._controller.set_autoconnect(False))
            finally:
                self._live_passphrase = None

            self._publish_notice(
                "info",
                "hotspot_updated",
                f"Hotspot {'started' if enabled else 'saved'} on {chosen_interface}.",
            )
            return await self._snapshot_unlocked()

    async def enable(self, confirm_uplink_loss: bool) -> HotspotSnapshot:
        """Bring the existing profile up, provisionally."""
        async with self._exclusive():
            await self._require_available()
            state = await self._require_configured()
            chosen_interface = await self._choose_interface(state.interface, confirm_uplink_loss)
            await self._activate_provisionally(chosen_interface)
            self._publish_notice("info", "hotspot_enabled", f"Hotspot is up on {chosen_interface}.")
            return await self._snapshot_unlocked()

    async def disable(self, confirm_uplink_loss: bool) -> HotspotSnapshot:
        """Bring the profile down and stop it coming back on boot."""
        async with self._exclusive():
            await self._require_available()
            await self._require_configured()
            await self._cancel_rollback()
            await self._guard(self._controller.deactivate())
            await self._guard(self._controller.set_autoconnect(False))
            self._publish_notice("info", "hotspot_disabled", "Hotspot is down.")
            return await self._snapshot_unlocked()

    async def confirm(self) -> HotspotSnapshot:
        """Keep the hotspot that is currently on trial, and make it survive reboot.

        This is the whole point of the commit-confirm dance: reaching this
        endpoint at all proves the API is still reachable with the hotspot
        running, which is exactly the thing that was in doubt.
        """
        async with self._exclusive():
            if self._rollback_task is None:
                raise HotspotError(
                    "no_pending_confirmation",
                    "There is no hotspot change waiting to be confirmed.",
                )
            await self._cancel_rollback()
            await self._guard(self._controller.set_autoconnect(True))
            self._publish_notice(
                "info", "hotspot_confirmed", "Hotspot confirmed; it will now start on boot."
            )
            return await self._snapshot_unlocked()

    async def forget(self) -> None:
        """Delete the profile entirely, forgetting the network name and password."""
        async with self._exclusive():
            await self._require_available()
            await self._cancel_rollback()
            await self._guard(self._controller.deactivate())
            await self._guard(self._controller.delete_profile())
            self._publish_notice("info", "hotspot_forgotten", "Hotspot configuration deleted.")

    async def close(self) -> None:
        """Cancel any pending rollback so shutdown leaves no orphaned task.

        Deliberately does *not* roll back on the way out: a container restart
        must not tear down a working hotspot. The activation simply stays
        unconfirmed, with autoconnect off, so it survives until the next reboot
        and no further — a stated bound of keeping this timer in-process.
        """
        await self._cancel_rollback()

    # ---------------------------------------------------------------- helpers

    @contextlib.asynccontextmanager
    async def _exclusive(self) -> AsyncIterator[None]:
        """Hold the mutation lock, fast-failing rather than queueing behind it."""
        if self._lock.locked():
            raise HotspotBusyError()
        async with self._lock:
            yield

    async def _require_available(self) -> None:
        """Refuse early when this host cannot control an access point."""
        if not await self._controller.is_available():
            raise HotspotUnavailableError(
                "This host cannot manage a WiFi hotspot: NetworkManager was not reachable."
            )

    async def _require_configured(self) -> HotspotRuntimeState:
        """Return the current profile, refusing when none exists yet."""
        state = await self._controller.read_state()
        if not state.profile_exists:
            raise HotspotError(
                "hotspot_not_configured",
                "Configure the hotspot's network name and password first.",
            )
        return state

    async def _choose_interface(self, requested: str | None, confirm_uplink_loss: bool) -> str:
        """Pick the interface to use, refusing to take the host's uplink unasked.

        Selection order is: what the request named, then what the deployment
        configured, then automatic. Automatic **never** picks an interface that
        is carrying a connection — the hotspot is strictly additive, and
        auto-selecting the uplink would make merely saving a configuration drop
        the operator's own link.
        """
        candidates = await self._controller.list_wireless_interfaces()
        if not candidates:
            raise HotspotError(
                "no_wireless_interface",
                "This host has no wireless interface that can host a network.",
            )

        named = requested or self._configured_interface
        if named is not None:
            match = next((entry for entry in candidates if entry.name == named), None)
            if match is None:
                raise HotspotError(
                    "interface_not_found",
                    f"No wireless interface named {named} was found.",
                    interface=named,
                    available=[entry.name for entry in candidates],
                )
            # `supports_ap is None` means this NetworkManager did not report the
            # capability at all — assume capable and let activation fail loudly,
            # rather than refusing on a version difference.
            if match.supports_ap is False:
                raise HotspotError(
                    "interface_ap_unsupported",
                    f"{named} cannot host a network; its driver does not support AP mode.",
                    interface=named,
                )
            self._refuse_uplink_loss_unless_confirmed(match, confirm_uplink_loss)
            return match.name

        free = [
            entry
            for entry in candidates
            if entry.supports_ap is not False
            and entry.active_connection_name is None
            and not entry.carries_default_route
        ]
        if free:
            return free[0].name

        # Everything capable is in use. Rather than silently taking one, name the
        # one we would take and make the operator say so.
        capable = [entry for entry in candidates if entry.supports_ap is not False]
        if not capable:
            raise HotspotError(
                "interface_ap_unsupported",
                "No wireless interface on this host supports hosting a network.",
            )
        self._refuse_uplink_loss_unless_confirmed(capable[0], confirm_uplink_loss)
        return capable[0].name

    def _refuse_uplink_loss_unless_confirmed(
        self, interface: WirelessInterface, confirm_uplink_loss: bool
    ) -> None:
        """Raise unless the operator has acknowledged losing this interface's connection.

        The gate is the **interface's** state, never the caller's address.
        `request.client.host` becomes a proxy's address behind any reverse
        proxy, so a caller-based check would silently fail *open* — exactly
        backwards for a guard whose whole job is preventing a lockout.
        """
        in_use = interface.active_connection_name is not None or interface.carries_default_route
        if not in_use or confirm_uplink_loss:
            return
        raise UplinkLossUnconfirmedError(
            "uplink_loss_unconfirmed",
            (
                f"{interface.name} is currently connected to "
                f"{interface.station_ssid or 'a network'}. Starting the hotspot will "
                "disconnect it. Confirm to continue."
            ),
            interface=interface.name,
            station_ssid=interface.station_ssid,
            carries_default_route=interface.carries_default_route,
        )

    async def _activate_provisionally(self, interface: str) -> None:
        """Bring the hotspot up and arm the rollback that undoes it if unconfirmed."""
        previous_connection = await self._controller.active_connection_on(interface)
        await self._cancel_rollback()
        await self._guard(self._controller.activate())
        self._rollback_target = previous_connection
        deadline_ms = self._clock.now_ms() + int(self._confirm_timeout_s * 1000)
        self._confirm_deadline_ms = deadline_ms
        self._rollback_task = asyncio.create_task(
            self._rollback_at(deadline_ms), name="hotspot-rollback"
        )

    async def _rollback_at(self, deadline_ms: int) -> None:
        """Wait until `deadline_ms`, then undo the activation.

        Sleeps toward the **deadline already published to the client** rather
        than for a fixed duration from whenever this task happens to get its
        first turn on the event loop. Those differ by microseconds in
        production, but they are not the same thing: the deadline is what
        `confirm_deadline_ms` promised an operator, and a rollback that fires
        measurably later than its own countdown said it would is a rollback
        nobody can reason about. It also means a deadline that has already
        passed by the time this starts rolls back immediately, rather than
        granting a second full window.

        Cancelled by `confirm()`. Any failure in here is published as a notice
        and swallowed: this runs detached, and a raised exception would vanish
        into the task with the operator none the wiser.
        """
        remaining_s = (deadline_ms - self._clock.now_ms()) / 1000
        if remaining_s > 0:
            await self._clock.sleep(remaining_s)

        try:
            await self._controller.set_autoconnect(False)
            await self._controller.deactivate()
            if self._rollback_target is not None:
                await self._controller.activate_named(self._rollback_target)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("hotspot rollback failed")
            self._publish_notice(
                "error",
                "hotspot_rollback_failed",
                "The hotspot was not confirmed, and restoring the previous connection failed. "
                "Check the Pi's network directly.",
            )
        else:
            self._publish_notice(
                "warn",
                "hotspot_rollback",
                "The hotspot was not confirmed in time and has been rolled back.",
            )
        finally:
            self._rollback_task = None
            self._confirm_deadline_ms = None
            self._rollback_target = None

    async def _cancel_rollback(self) -> None:
        """Cancel and await any armed rollback, leaving no task behind."""
        task = self._rollback_task
        self._rollback_task = None
        self._confirm_deadline_ms = None
        self._rollback_target = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _guard(self, operation: Coroutine[Any, Any, None]) -> None:
        """Await a controller call, translating its failures into `HotspotError`.

        Records the failure so `GET /api/hotspot` can explain a hotspot that is
        not up, and scrubs the in-flight passphrase out of any command output
        before it reaches an operator, a log record or an SSE notice — `nmcli`
        can echo a property value back inside a parse error.
        """
        try:
            await operation
        except WifiApUnavailableError as error:
            raise HotspotUnavailableError(str(error)) from error
        except WifiApTimeoutError as error:
            raise self._record_failure(
                HotspotError(
                    "hotspot_command_timeout",
                    "The network command did not finish in time.",
                    stderr_tail=self._scrub(error.stderr_tail),
                )
            ) from error
        except WifiApCommandError as error:
            raise self._record_failure(
                HotspotError(
                    "hotspot_command_failed",
                    "The network command failed.",
                    stderr_tail=self._scrub(error.stderr_tail),
                )
            ) from error

    def _scrub(self, text: str | None) -> str | None:
        """Remove the in-flight passphrase from command output, if it is in there."""
        if text is None or not self._live_passphrase:
            return text
        return text.replace(self._live_passphrase, "***")

    def _record_failure(self, error: HotspotError) -> HotspotError:
        """Remember a failure for the next snapshot, and return it for raising."""
        self._last_error = (error.code, error.message, self._clock.now_ms())
        return error

    async def _snapshot_unlocked(self) -> HotspotSnapshot:
        """Build a snapshot from inside a held lock, without re-acquiring it."""
        available = await self._controller.is_available()
        state = await self._controller.read_state()
        uplink_collision = False
        if state.interface:
            uplink_collision = await self._interface_is_carrying_uplink(state.interface)
        return HotspotSnapshot(
            available=available,
            state=state,
            uplink_interface_is_hotspot_interface=uplink_collision,
            pending_confirmation=self._rollback_task is not None,
            confirm_deadline_ms=self._confirm_deadline_ms,
            last_error=self._last_error,
        )

    async def _interface_is_carrying_uplink(self, interface_name: str) -> bool:
        """Whether `interface_name` is also the host's own way onto the network.

        True here is what drives the "you are about to cut your own link"
        warning in the UI. Reported even while the hotspot is already up, since
        that is precisely when an operator wants to understand why the Pi is no
        longer on the house network.
        """
        for entry in await self._controller.list_wireless_interfaces():
            if entry.name != interface_name:
                continue
            return entry.carries_default_route or entry.active_connection_name is not None
        return False

    def _publish_notice(self, level: str, code: str, message: str) -> None:
        """Publish one operator-facing notice on the existing SSE `notice` event.

        Deliberately reuses `notice` rather than introducing a hotspot event
        name: `_PUBLIC_EVENT_NAMES` in `routers/events.py` stays untouched, so
        every existing client tolerates this without a change (ADR-0007 — the
        feature is strictly additive).
        """
        self._event_bus.publish(
            SseMessage(
                event="notice",
                data=NoticeItem(
                    level=level,  # type: ignore[arg-type]
                    code=code,
                    message=message,
                    device_id=None,
                    ts=self._clock.now_ms(),
                ),
            )
        )
