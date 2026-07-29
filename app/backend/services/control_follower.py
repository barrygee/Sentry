"""One NDJSON follower connection per running relay's `P+2` (architecture §4.3, §7.5).

Connects, **never claims the token**, reads `state` events, and feeds live
tuning into the registry — this is how the UI shows real tuning without
fighting Sentinel for ownership. Briefly claims the token only to apply an
operator's live retune (`center_hz`/`sample_rate`/`gain_db`/`gain_auto`),
then releases it.

**Transport note.** There is no existing `interfaces`/`adapters` seam for a
plain TCP NDJSON client (only the USB/process/rtlsdr/netprobe Protocols are
defined, and `adapters/` is out of this module's ownership for this change),
so this module talks to the relay's control port directly via
`asyncio.open_connection`/`asyncio.StreamReader`/`StreamWriter` — the same
high-level asyncio stream primitives `app.backend.relay.rtl_tcp_relay` itself
uses for this exact protocol, as opposed to the raw `socket` module. Flagged
in the Phase 2A handoff as worth promoting to a proper `ControlChannelClient`
Protocol + adapter in a follow-up.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field

from app.backend.interfaces.clock import Clock
from app.backend.schemas.device import TunerInfo
from app.backend.services.device_registry import DeviceRegistry

_logger = logging.getLogger(__name__)

FOLLOWER_BACKOFF_START_S = 1.0
FOLLOWER_BACKOFF_MAX_S = 30.0

CLAIM_RESPONSE_TIMEOUT_S = 2.0
"""How long `apply_tune` waits for the relay's response to a `claim` before giving up."""


@dataclass(frozen=True, slots=True)
class TuneRequest:
    """A live-retune request applied via a brief claim/set/release round-trip."""

    center_hz: int | None = None
    sample_rate: int | None = None
    gain_db: float | None = None
    gain_auto: bool | None = None


@dataclass(frozen=True, slots=True)
class TuneOutcome:
    """The result of `ControlFollowerService.apply_tune()`."""

    applied: bool
    """False when another owner already held the token — the request was deferred."""

    tuning_deferred: bool
    """Mirrors `applied is False`; the value is applied at the pair's next start."""


@dataclass(slots=True)
class _FollowerSession:
    """One device's follower connection and its claim/release coordination state."""

    host: str
    control_port: int
    writer: asyncio.StreamWriter | None = None
    run_task: asyncio.Task[None] | None = None
    stop_requested: bool = False
    tune_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_state_future: asyncio.Future[dict[str, object]] | None = None
    """Resolved by the read loop with the next parsed `state` message, so
    `apply_tune` can correlate the relay's response to its own `claim`."""


class ControlFollowerService:
    """Maintains one read-mostly NDJSON connection per running device pair."""

    def __init__(self, device_registry: DeviceRegistry, clock: Clock) -> None:
        self._device_registry = device_registry
        self._clock = clock
        self._sessions: dict[str, _FollowerSession] = {}

    async def start_following(self, device_id: str, host: str, control_port: int) -> None:
        """Begin (or restart) the follower connection for one device's control port.

        Runs until `stop_following` is called or the pair stops; reconnects
        with capped backoff on any drop, and never sends an unsolicited
        `claim`. Idempotent: calling this again for an already-following
        device is a no-op (call `stop_following` first to reconnect to a new
        `host`/`control_port`, e.g. after the pair itself restarted).
        """
        if device_id in self._sessions:
            return
        session = _FollowerSession(host=host, control_port=control_port)
        self._sessions[device_id] = session
        session.run_task = asyncio.create_task(
            self._run_session(device_id, session), name=f"control-follower-{device_id}"
        )

    async def stop_following(self, device_id: str) -> None:
        """Stop and release the follower connection for one device, if any."""
        session = self._sessions.pop(device_id, None)
        if session is None:
            return
        session.stop_requested = True
        if session.writer is not None:
            with contextlib.suppress(OSError):
                session.writer.close()
        if session.run_task is not None:
            session.run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.run_task

    async def apply_tune(self, device_id: str, request: TuneRequest) -> TuneOutcome:
        """Claim the token, issue one `set`, and release — for an operator-initiated retune.

        Returns `tuning_deferred=True` without touching the dongle if another
        owner (typically a live Sentinel session) currently holds the token,
        or if this device has no live follower connection at all (the pair
        is not currently running). The release is always attempted, even if
        `set` itself raised, so a transient write error can never leave the
        token stuck held.
        """
        session = self._sessions.get(device_id)
        if session is None or session.writer is None:
            return TuneOutcome(applied=False, tuning_deferred=True)

        async with session.tune_lock:
            loop = asyncio.get_running_loop()
            response_future: asyncio.Future[dict[str, object]] = loop.create_future()
            session.pending_state_future = response_future
            claimed = False
            try:
                await self._send(session, {"op": "claim"})
                try:
                    response = await asyncio.wait_for(
                        response_future, timeout=CLAIM_RESPONSE_TIMEOUT_S
                    )
                except TimeoutError:
                    return TuneOutcome(applied=False, tuning_deferred=True)
                if not response.get("owner"):
                    return TuneOutcome(applied=False, tuning_deferred=True)
                claimed = True

                tune_fields = {
                    field_name: field_value
                    for field_name, field_value in (
                        ("center_hz", request.center_hz),
                        ("sample_rate", request.sample_rate),
                        ("gain_db", request.gain_db),
                        ("gain_auto", request.gain_auto),
                    )
                    if field_value is not None
                }
                await self._send(session, {"op": "set", **tune_fields})
                return TuneOutcome(applied=True, tuning_deferred=False)
            finally:
                session.pending_state_future = None
                if claimed:
                    with contextlib.suppress(OSError):
                        await self._send(session, {"op": "release"})

    async def _send(self, session: _FollowerSession, message: dict[str, object]) -> None:
        """Write one NDJSON message to the session's writer, raising `OSError` on failure."""
        if session.writer is None:
            raise OSError("control follower has no open connection")
        session.writer.write((json.dumps(message) + "\n").encode("utf-8"))
        await session.writer.drain()

    async def _run_session(self, device_id: str, session: _FollowerSession) -> None:
        """Connect, read NDJSON lines forever, and reconnect with backoff on any drop."""
        backoff_s = FOLLOWER_BACKOFF_START_S
        while not session.stop_requested:
            try:
                reader, writer = await asyncio.open_connection(session.host, session.control_port)
            except OSError:
                await self._clock.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, FOLLOWER_BACKOFF_MAX_S)
                continue

            session.writer = writer
            backoff_s = FOLLOWER_BACKOFF_START_S
            try:
                await self._read_until_closed(device_id, session, reader)
            finally:
                session.writer = None
                with contextlib.suppress(OSError):
                    writer.close()

            if session.stop_requested:
                return
            await self._clock.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, FOLLOWER_BACKOFF_MAX_S)

    async def _read_until_closed(
        self, device_id: str, session: _FollowerSession, reader: asyncio.StreamReader
    ) -> None:
        """Read and dispatch NDJSON lines until the peer closes or an error occurs."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return  # peer closed its half of the connection
                self._dispatch_line(device_id, session, line)
        except (OSError, ConnectionError):
            return

    def _dispatch_line(self, device_id: str, session: _FollowerSession, line: bytes) -> None:
        """Parse and act on one NDJSON line, never raising for a malformed one."""
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        if message.get("event") != "state":
            return

        pending_future = session.pending_state_future
        if pending_future is not None and not pending_future.done():
            pending_future.set_result(message)

        try:
            tuner = TunerInfo(
                center_hz=int(message["center_hz"]),
                sample_rate=int(message["sample_rate"]),
                gain_db=float(message["gain_db"]),
                gain_auto=bool(message["gain_auto"]),
                locked=bool(message.get("locked", False)),
                observed_at=self._clock.now_ms(),
            )
        except (KeyError, TypeError, ValueError):
            _logger.debug("control follower %s: malformed state message %r", device_id, message)
            return
        self._device_registry.update_tuner_state(device_id, tuner)
