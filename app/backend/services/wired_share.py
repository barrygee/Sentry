"""Wired-sharing lifecycle: configure, raise, roll back (ADR-0014).

The wired twin of `services/hotspot.py`, and it touches no OS primitive of its
own for the same reason: everything hardware-facing goes through the injected
`WiredShareController`, so the two genuinely interesting behaviours — the
refusal to silently drop the host's own uplink, and the commit-confirm rollback
timer — are testable on a laptop with no NetworkManager.

**Why the rollback timer matters even more here than for the hotspot.** On the
target Pi the wired port *is* the uplink. Sharing `eth0` therefore does not
merely risk dropping the Pi's LAN connection, it drops it by definition: the
port stops being a DHCP client of the house router and starts being a DHCP
server for whatever is plugged into it. If the operator is browsing the console
over that same LAN, the page they are looking at goes with it. So an activation
is provisional: it reverts itself unless someone calls `confirm()` from the
other side, which can only happen if the API is still reachable — over the
cable, over the hotspot, or over a second interface. Confirming is the proof;
nothing else is.

**There is no secret anywhere in this service.** No passphrase to scrub out of
command output, no write-only field, no `_live_passphrase`. The cable is the
credential — which is a real security property worth stating, not an omission:
reaching this network requires physical access to the port.
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
    HotspotClient,
    WiredInterface,
    WiredShareProfile,
    WiredShareRuntimeState,
)
from app.backend.interfaces.wired_share import (
    WiredShareCommandError,
    WiredShareController,
    WiredShareTimeoutError,
    WiredShareUnavailableError,
)
from app.backend.schemas.events import NoticeItem
from app.backend.services.event_bus import EventBus, SseMessage

_logger = logging.getLogger(__name__)


class WiredError(Exception):
    """A wired-sharing operation the router should translate into an error response.

    Carries the machine-readable `code` and any context the operator needs, so
    the router maps it to the uniform `{"detail": {...}}` envelope without
    re-deriving anything.
    """

    def __init__(self, code: str, message: str, **context: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


class WiredBusyError(WiredError):
    """Another wired-sharing operation is already running."""

    def __init__(self) -> None:
        super().__init__(
            "wired_busy",
            "Another wired-sharing change is in progress. Wait for it to finish and try again.",
        )


class WiredUnavailableError(WiredError):
    """This host cannot share a wired port at all."""

    def __init__(self, reason: str) -> None:
        super().__init__("wired_unavailable", reason)


class WiredUplinkLossUnconfirmedError(WiredError):
    """The operation would drop a connection currently in use, and nobody said it could."""


@dataclass(frozen=True, slots=True)
class WiredShareSnapshot:
    """Everything the API layer needs to describe wired sharing in one response.

    Assembled here rather than in the router so the "what is true right now"
    question has exactly one answer, shared by `GET /api/wired` and by every
    mutator's success body.
    """

    available: bool
    state: WiredShareRuntimeState
    uplink_interface_is_share_interface: bool
    carrier_up: bool | None
    """Whether a cable is plugged into the shared port. `None` means the host did
    not say, which must not be rendered as "unplugged" — an empty client list
    with an unknown carrier is a different story from one with a dead link."""
    pending_confirmation: bool
    confirm_deadline_ms: int | None
    last_error: tuple[str, str, int, str | None] | None
    """`(code, message, unix_ms, stderr_tail)`. The tail is the command output
    that says *why* NetworkManager refused — without it the UI can only report
    that something failed."""


class WiredShareService:
    """Owns Sentry's single wired-sharing profile and its provisional activations."""

    def __init__(
        self,
        controller: WiredShareController,
        event_bus: EventBus,
        clock: Clock,
        default_gateway_cidr: str,
        confirm_timeout_s: float,
        configured_interface: str | None,
        wired_connection_name: str,
    ) -> None:
        self._controller = controller
        self._event_bus = event_bus
        self._clock = clock
        self._default_gateway_cidr = default_gateway_cidr
        self._confirm_timeout_s = confirm_timeout_s
        self._configured_interface = configured_interface
        # Needed to tell "something else is using this port" apart from "our own
        # share is" — NetworkManager reports both the same way, as the
        # interface's active connection.
        self._wired_connection_name = wired_connection_name

        self._lock = asyncio.Lock()
        """Serialises every mutation across the whole process.

        Held for the duration of a change, and probed rather than awaited by
        callers — a queue of pending `nmcli` invocations behind a wedged one is
        strictly worse than a fast `409`. Sentry is a single process by
        construction (ADR-0001), so an in-process lock is a complete fix here.

        Deliberately *not* shared with `HotspotService`'s lock. The two features
        drive different interfaces through different profiles, and coupling them
        would mean a wedged radio blocking a change to the Ethernet port that an
        operator might be making precisely because the radio is wedged.
        """

        self._rollback_task: asyncio.Task[None] | None = None
        self._confirm_deadline_ms: int | None = None
        self._rollback_target: str | None = None
        self._last_error: tuple[str, str, int, str | None] | None = None

    # ------------------------------------------------------------------ reads

    async def get_snapshot(self) -> WiredShareSnapshot:
        """Describe wired sharing as it is right now.

        Never raises. A host that cannot do any of this answers with
        `available=False` and an absent profile, which is what lets
        `GET /api/wired` stay a 200 instead of failing.
        """
        return await self._snapshot_unlocked()

    @property
    def wired_connection_name(self) -> str:
        """The NetworkManager profile this Sentry's own wired share uses.

        Exposed so callers can tell "another connection is using this port" from
        "our own share is". NetworkManager reports both the same way.
        """
        return self._wired_connection_name

    @property
    def default_gateway_cidr(self) -> str:
        """The Pi-side address used when a request does not name one."""
        return self._default_gateway_cidr

    async def list_interfaces(self) -> tuple[WiredInterface, ...]:
        """List Ethernet interfaces the operator could share."""
        return await self._controller.list_wired_interfaces()

    async def list_clients(self) -> tuple[HotspotClient, ...] | None:
        """List the share's DHCP leases. `None` means unknown, never zero.

        Scoped to the profile's own interface so a hotspot running at the same
        time does not have its WiFi clients listed here as cabled machines. A
        profile with no interface has no leases of its own, so it answers
        "unknown" rather than borrowing another interface's.
        """
        state = await self._controller.read_state()
        if state.interface is None:
            return None
        return self._controller.list_clients(state.interface)

    async def release_lease(self, mac_address: str) -> None:
        """Forget one DHCP lease, identified by the client's MAC address.

        The address to release is looked up from the lease list rather than
        taken from the caller: a request naming both would let one machine's MAC
        be paired with another's IP, and `dhcp_release` would act on that pair
        without question.

        Refuses when sharing is not up. dnsmasq only exists while the shared
        connection is active, so a release sent to a stopped share has nothing
        listening and would fail opaquely rather than say why.
        """
        async with self._exclusive():
            await self._require_available()
            state = await self._controller.read_state()
            if not state.active or state.interface is None:
                raise WiredError(
                    "wired_not_running",
                    "Wired sharing is not running, so it has no leases to release.",
                )

            clients = self._controller.list_clients(state.interface)
            if clients is None:
                raise WiredError(
                    "leases_unreadable",
                    "This Sentry cannot read its lease file, so it cannot release a lease.",
                )

            normalised = mac_address.strip().lower()
            match = next(
                (client for client in clients if client.mac_address.lower() == normalised), None
            )
            if match is None:
                raise WiredError(
                    "lease_not_found",
                    "That lease is no longer listed — it may have expired or "
                    "already been released.",
                )

            await self._guard(
                self._controller.release_lease(state.interface, match.ip_address, match.mac_address)
            )
            self._publish_notice(
                "info",
                "wired_lease_released",
                f"Released the wired lease for {match.ip_address}.",
            )

    # -------------------------------------------------------------- mutations

    async def apply_configuration(
        self,
        *,
        enabled: bool,
        interface: str | None,
        gateway_cidr: str | None,
        confirm_uplink_loss: bool,
    ) -> WiredShareSnapshot:
        """Write the profile, then bring it up or down to match `enabled`.

        Far shorter than the hotspot's equivalent, and the difference is
        entirely the absence of a secret: there is no "keep the stored
        passphrase" path to get right, and no case where a new profile would
        come up unprotected, because the port's protection is the cable.
        """
        async with self._exclusive():
            await self._require_available()
            chosen_interface = await self._choose_interface(interface, confirm_uplink_loss)
            profile = WiredShareProfile(
                gateway_cidr=gateway_cidr or self._default_gateway_cidr,
                interface=chosen_interface,
                # Never set on a write. Persistence across reboot is earned by
                # confirming the activation, not by asking for it.
                autoconnect=False,
            )

            await self._guard(self._controller.apply_profile(profile))
            if enabled:
                await self._activate_provisionally(chosen_interface)
            else:
                await self._cancel_rollback()
                await self._guard(self._controller.deactivate())
                await self._guard(self._controller.set_autoconnect(False))

            self._publish_notice(
                "info",
                "wired_updated",
                f"Wired sharing {'started' if enabled else 'saved'} on {chosen_interface}.",
            )
            return await self._snapshot_unlocked()

    async def enable(self, confirm_uplink_loss: bool) -> WiredShareSnapshot:
        """Bring the existing profile up, provisionally."""
        async with self._exclusive():
            await self._require_available()
            state = await self._require_configured()
            chosen_interface = await self._choose_interface(state.interface, confirm_uplink_loss)
            await self._activate_provisionally(chosen_interface)
            self._publish_notice(
                "info", "wired_enabled", f"Wired sharing is up on {chosen_interface}."
            )
            return await self._snapshot_unlocked()

    async def disable(self, confirm_uplink_loss: bool) -> WiredShareSnapshot:
        """Bring the profile down and stop it coming back on boot.

        Note what this does *not* do: it does not restore whatever profile was
        on the port beforehand. NetworkManager brings the port's own
        autoconnecting profile back once ours is down, which on the target Pi is
        the DHCP client that had the LAN address — the same mechanism a rollback
        relies on, minus the explicit `activate_named`, because here the
        operator is present and watching rather than absent and timed out.
        """
        async with self._exclusive():
            await self._require_available()
            await self._require_configured()
            await self._cancel_rollback()
            await self._guard(self._controller.deactivate())
            await self._guard(self._controller.set_autoconnect(False))
            self._publish_notice("info", "wired_disabled", "Wired sharing is down.")
            return await self._snapshot_unlocked()

    async def confirm(self) -> WiredShareSnapshot:
        """Keep the share that is currently on trial, and make it survive reboot.

        Reaching this endpoint at all proves the API is still reachable with
        sharing running, which is exactly the thing that was in doubt.
        """
        async with self._exclusive():
            if self._rollback_task is None:
                raise WiredError(
                    "no_pending_confirmation",
                    "There is no wired-sharing change waiting to be confirmed.",
                )
            await self._cancel_rollback()
            await self._guard(self._controller.set_autoconnect(True))
            self._publish_notice(
                "info",
                "wired_confirmed",
                "Wired sharing confirmed; it will now start on boot.",
            )
            return await self._snapshot_unlocked()

    async def forget(self) -> None:
        """Delete the profile entirely."""
        async with self._exclusive():
            await self._require_available()
            await self._cancel_rollback()
            await self._guard(self._controller.deactivate())
            await self._guard(self._controller.delete_profile())
            self._publish_notice("info", "wired_forgotten", "Wired-sharing configuration deleted.")

    async def close(self) -> None:
        """Cancel any pending rollback so shutdown leaves no orphaned task.

        Deliberately does *not* roll back on the way out: a container restart
        must not tear down a working share, which may well be the only way the
        operator can currently reach this Sentry. The activation simply stays
        unconfirmed, with autoconnect off, so it survives until the next reboot
        and no further.
        """
        await self._cancel_rollback()

    # ---------------------------------------------------------------- helpers

    @contextlib.asynccontextmanager
    async def _exclusive(self) -> AsyncIterator[None]:
        """Hold the mutation lock, fast-failing rather than queueing behind it."""
        if self._lock.locked():
            raise WiredBusyError()
        async with self._lock:
            yield

    async def _require_available(self) -> None:
        """Refuse early when this host cannot share a wired port."""
        if not await self._controller.is_available():
            raise WiredUnavailableError(
                "This host cannot share an Ethernet port: NetworkManager was not reachable."
            )

    async def _require_configured(self) -> WiredShareRuntimeState:
        """Return the current profile, refusing when none exists yet."""
        state = await self._controller.read_state()
        if not state.profile_exists:
            raise WiredError(
                "wired_not_configured",
                "Choose which Ethernet port to share and save it first.",
            )
        return state

    async def _choose_interface(self, requested: str | None, confirm_uplink_loss: bool) -> str:
        """Pick the port to share, refusing to take the host's uplink unasked.

        Selection order is: what the request named, then what the deployment
        configured, then automatic. Automatic **never** picks a port that is
        carrying a connection — on a one-port Pi that means automatic selection
        finds nothing and the operator has to name `eth0` and tick the
        acknowledgement, which is the correct outcome: taking the Pi's only LAN
        link is not a thing to do on a shrug.
        """
        candidates = await self._controller.list_wired_interfaces()
        if not candidates:
            raise WiredError(
                "no_wired_interface",
                "This host has no Ethernet port that could be shared.",
            )

        named = requested or self._configured_interface
        if named is not None:
            match = next((entry for entry in candidates if entry.name == named), None)
            if match is None:
                raise WiredError(
                    "interface_not_found",
                    f"No Ethernet port named {named} was found.",
                    interface=named,
                    available=[entry.name for entry in candidates],
                )
            self._refuse_uplink_loss_unless_confirmed(match, confirm_uplink_loss)
            return match.name

        free = [
            entry
            for entry in candidates
            if entry.active_connection_name is None and not entry.carries_default_route
        ]
        if free:
            return free[0].name

        # Everything is in use. Rather than silently taking one, name the one we
        # would take and make the operator say so.
        self._refuse_uplink_loss_unless_confirmed(candidates[0], confirm_uplink_loss)
        return candidates[0].name

    def _refuse_uplink_loss_unless_confirmed(
        self, interface: WiredInterface, confirm_uplink_loss: bool
    ) -> None:
        """Raise unless the operator has acknowledged losing this port's connection.

        The gate is the **port's** state, never the caller's address.
        `request.client.host` becomes a proxy's address behind any reverse proxy,
        so a caller-based check would silently fail *open* — exactly backwards
        for a guard whose whole job is preventing a lockout.
        """
        in_use = interface.active_connection_name is not None or interface.carries_default_route
        if not in_use or confirm_uplink_loss:
            return
        raise WiredUplinkLossUnconfirmedError(
            "uplink_loss_unconfirmed",
            (
                f"{interface.name} is currently carrying this Sentry's own network "
                f"connection ({interface.active_connection_name or 'the default route'}). "
                "Sharing it will disconnect the Pi from that network. Confirm to continue."
            ),
            interface=interface.name,
            active_connection_name=interface.active_connection_name,
            carries_default_route=interface.carries_default_route,
        )

    async def _activate_provisionally(self, interface: str) -> None:
        """Bring sharing up and arm the rollback that undoes it if unconfirmed."""
        previous_connection = await self._controller.active_connection_on(interface)
        await self._cancel_rollback()
        await self._guard(self._controller.activate())
        self._rollback_target = previous_connection
        deadline_ms = self._clock.now_ms() + int(self._confirm_timeout_s * 1000)
        self._confirm_deadline_ms = deadline_ms
        self._rollback_task = asyncio.create_task(
            self._rollback_at(deadline_ms), name="wired-share-rollback"
        )

    async def _rollback_at(self, deadline_ms: int) -> None:
        """Wait until `deadline_ms`, then undo the activation.

        Sleeps toward the **deadline already published to the client** rather
        than for a fixed duration from whenever this task gets its first turn on
        the event loop: the deadline is what `confirm_deadline_ms` promised the
        operator, and a rollback that fires later than its own countdown said it
        would is one nobody can reason about.

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
            _logger.exception("wired-sharing rollback failed")
            self._publish_notice(
                "error",
                "wired_rollback_failed",
                "Wired sharing was not confirmed, and restoring the previous connection "
                "failed. Check the Pi's network directly.",
            )
        else:
            self._publish_notice(
                "warn",
                "wired_rollback",
                "Wired sharing was not confirmed in time and has been rolled back.",
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
        """Await a controller call, translating its failures into `WiredError`.

        Records the failure so `GET /api/wired` can explain a share that is not
        up. No scrubbing step, unlike the hotspot's equivalent: nothing this
        service sends nmcli is a secret, so there is nothing for the command's
        output to leak back.
        """
        try:
            await operation
        except WiredShareUnavailableError as error:
            raise WiredUnavailableError(str(error)) from error
        except WiredShareTimeoutError as error:
            raise self._record_failure(
                WiredError(
                    "wired_command_timeout",
                    "The network command did not finish in time.",
                    stderr_tail=error.stderr_tail,
                )
            ) from error
        except WiredShareCommandError as error:
            raise self._record_failure(
                WiredError(
                    "wired_command_failed",
                    "The network command failed.",
                    stderr_tail=error.stderr_tail,
                )
            ) from error

    def _record_failure(self, error: WiredError) -> WiredError:
        """Remember a failure for the next snapshot, log its detail, and return it.

        The `stderr_tail` is the only thing that says *why* nmcli refused, so it
        is kept rather than discarded — the same lesson `HotspotService` learned
        the hard way, applied here from the start.
        """
        stderr_tail = error.context.get("stderr_tail")
        stderr_text = stderr_tail if isinstance(stderr_tail, str) else None
        if stderr_text:
            _logger.warning("wired %s: %s", error.code, stderr_text)
        else:
            _logger.warning("wired %s: %s (no command output)", error.code, error.message)
        self._last_error = (error.code, error.message, self._clock.now_ms(), stderr_text)
        return error

    async def _snapshot_unlocked(self) -> WiredShareSnapshot:
        """Build a snapshot without acquiring the mutation lock.

        Safe to call from inside a held lock and from a plain read alike, which
        is why `get_snapshot()` simply delegates here rather than duplicating it.
        """
        available = await self._controller.is_available()
        state = await self._controller.read_state()
        uplink_collision = False
        carrier_up: bool | None = None
        if state.interface:
            uplink_collision, carrier_up = await self._describe_share_interface(state.interface)
        return WiredShareSnapshot(
            available=available,
            state=state,
            uplink_interface_is_share_interface=uplink_collision,
            carrier_up=carrier_up,
            pending_confirmation=self._rollback_task is not None,
            confirm_deadline_ms=self._confirm_deadline_ms,
            last_error=self._last_error,
        )

    async def _describe_share_interface(self, interface_name: str) -> tuple[bool, bool | None]:
        """Return `(is_also_the_uplink, carrier_up)` for the shared port.

        Both come from one enumeration rather than two, because they are read at
        the same moment for the same interface and a second call could observe a
        different one — a cable pulled between the two reads would produce a
        snapshot claiming a live link on a port that no longer has one.

        Our own profile does not count as an uplink. NetworkManager reports it
        as the port's active connection while sharing is up, and treating any
        active connection as an uplink would show the "you are about to cut your
        own link" warning *because* sharing had started — the exact mistake the
        hotspot made and had to fix. A real default route still counts, since a
        port routing the host's traffic is an uplink whatever profile is doing it.
        """
        for entry in await self._controller.list_wired_interfaces():
            if entry.name != interface_name:
                continue
            is_uplink = entry.carries_default_route or (
                entry.active_connection_name is not None
                and entry.active_connection_name != self._wired_connection_name
            )
            return is_uplink, entry.carrier_up
        return False, None

    def _publish_notice(self, level: str, code: str, message: str) -> None:
        """Publish one operator-facing notice on the existing SSE `notice` event.

        Deliberately reuses `notice` rather than introducing a wired event name:
        `_PUBLIC_EVENT_NAMES` in `routers/events.py` stays untouched, so every
        existing client tolerates this without a change — the same additivity
        rule ADR-0007 set for the hotspot.
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
