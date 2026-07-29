"""A fake `rtl_tcp` server: no hardware, but the real wire protocol.

This is what lets the *unmodified* `rtl_tcp_relay.py` be exercised end to end
in a test with no physical dongle: point the relay's `RELAY_UPSTREAM_HOST`/
`RELAY_UPSTREAM_PORT` at this server instead of a real `rtl_tcp`, and the
relay cannot tell the difference (architecture §4.2, §12.9).

Wire protocol modelled (matches real `rtl_tcp`):
  - On connect, the server immediately writes a 12-byte "dongle info" header:
    4-byte ASCII magic `b"RTL0"`, a 4-byte big-endian tuner type, and a
    4-byte big-endian tuner gain count.
  - After the header, the server streams continuous synthetic IQ bytes.
  - The client may send 5-byte commands at any time: 1 command-id byte
    followed by a 4-byte big-endian parameter. Received commands are
    recorded for test assertions; this fake does not act on them (the relay
    does not depend on the upstream tuner actually retuning).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from dataclasses import dataclass, field
from typing import Literal

RTL_TCP_MAGIC = b"RTL0"
DONGLE_INFO_HEADER_SIZE = 12
COMMAND_SIZE = 5
DEFAULT_TUNER_TYPE = 1
DEFAULT_TUNER_GAIN_COUNT = 29

FakeRtlTcpMode = Literal["normal", "wedge", "no_header", "refuse_connection", "drop_after_n_bytes"]
"""The scripted behaviours this fake can exhibit, per architecture §12.9:

- "normal": send the header, then stream IQ bytes, honouring commands.
- "wedge": accept the TCP connection but never send anything — models a
  hung upstream, driving the relay's watchdog wedge-exit path.
- "no_header": accept the connection and stream IQ bytes immediately,
  skipping the 12-byte header — a malformed-upstream negative case.
- "refuse_connection": close the connection immediately after accepting it.
- "drop_after_n_bytes": send the header then exactly `drop_after_bytes` of
  IQ data before closing the connection — models a mid-stream disconnect.
"""


@dataclass(slots=True)
class RecordedConnection:
    """One client connection accepted by the fake server, for test assertions."""

    commands: list[bytes] = field(default_factory=list)
    """Every 5-byte command received on this connection, in order."""

    bytes_sent: int = 0
    """Total IQ payload bytes streamed on this connection (excludes the header)."""


def _synthetic_iq_chunk(chunk_index: int, chunk_size: int) -> bytes:
    """Generate one deterministic, non-constant chunk of fake 8-bit IQ samples.

    Deterministic (a function of `chunk_index`, not wall-clock or randomness)
    so a test can assert on exact bytes received; non-constant so a naive
    "did any bytes arrive" assertion cannot pass on an all-zero stream by
    accident.
    """
    return bytes((chunk_index + offset) % 256 for offset in range(chunk_size))


class FakeRtlTcpServer:
    """An asyncio TCP server that speaks just enough of the `rtl_tcp` wire protocol.

    Controllable from a test via the constructor's `mode` and streaming
    parameters, and via `set_mode()` for tests that change behaviour after
    starting the server (e.g. simulating a wedge partway through a run).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        mode: FakeRtlTcpMode = "normal",
        chunk_size: int = 4096,
        stream_interval_s: float = 0.05,
        drop_after_bytes: int = 0,
        tuner_type: int = DEFAULT_TUNER_TYPE,
        tuner_gain_count: int = DEFAULT_TUNER_GAIN_COUNT,
    ) -> None:
        """`port=0` binds an ephemeral port, read back afterwards via `port`."""
        self._host = host
        self._requested_port = port
        self._mode = mode
        self._chunk_size = chunk_size
        self._stream_interval_s = stream_interval_s
        self._drop_after_bytes = drop_after_bytes
        self._tuner_type = tuner_type
        self._tuner_gain_count = tuner_gain_count
        self._server: asyncio.base_events.Server | None = None
        self.connections: list[RecordedConnection] = []
        """Every connection ever accepted, retained for the life of the server."""

    @property
    def port(self) -> int:
        """The bound TCP port, resolved after `start()` even when `port=0` was requested."""
        if self._server is None or not self._server.sockets:
            raise RuntimeError("FakeRtlTcpServer has not been started")
        return int(self._server.sockets[0].getsockname()[1])

    def set_mode(self, mode: FakeRtlTcpMode, drop_after_bytes: int | None = None) -> None:
        """Change behaviour for connections accepted after this call.

        Existing open connections are unaffected — this only changes how
        *future* `handle_connection` calls behave, matching a test's need to
        simulate "the upstream started wedging" between two client
        connections.
        """
        self._mode = mode
        if drop_after_bytes is not None:
            self._drop_after_bytes = drop_after_bytes

    async def start(self) -> None:
        """Start listening. Must be called before `port` or `stop()`."""
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._requested_port
        )

    async def stop(self) -> None:
        """Stop listening and release the socket. Idempotent."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def __aenter__(self) -> FakeRtlTcpServer:
        await self.start()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.stop()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Dispatch one accepted connection according to the current `mode`.

        Each mode is a short, self-contained branch; the command-reader task
        is shared by every mode that stays open, since a real client may send
        commands regardless of what the fake chooses to stream back.
        """
        connection = RecordedConnection()
        self.connections.append(connection)
        try:
            if self._mode == "refuse_connection":
                return
            if self._mode == "wedge":
                await self._drain_commands_until_closed(reader, connection)
                return

            if self._mode != "no_header":
                writer.write(
                    RTL_TCP_MAGIC
                    + self._tuner_type.to_bytes(4, "big")
                    + self._tuner_gain_count.to_bytes(4, "big")
                )
                await writer.drain()

            command_reader_task = asyncio.create_task(
                self._drain_commands_until_closed(reader, connection)
            )
            try:
                await self._stream_iq(writer, connection)
            finally:
                command_reader_task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError
                ):
                    await command_reader_task
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    async def _stream_iq(
        self, writer: asyncio.StreamWriter, connection: RecordedConnection
    ) -> None:
        """Write synthetic IQ chunks until the connection closes or the byte budget is spent."""
        for chunk_index in itertools.count():
            if self._mode == "drop_after_n_bytes" and connection.bytes_sent >= (
                self._drop_after_bytes
            ):
                return
            chunk = _synthetic_iq_chunk(chunk_index, self._chunk_size)
            if self._mode == "drop_after_n_bytes":
                remaining = self._drop_after_bytes - connection.bytes_sent
                chunk = chunk[:remaining]
            writer.write(chunk)
            await writer.drain()
            connection.bytes_sent += len(chunk)
            await asyncio.sleep(self._stream_interval_s)

    async def _drain_commands_until_closed(
        self, reader: asyncio.StreamReader, connection: RecordedConnection
    ) -> None:
        """Read and record 5-byte commands until the peer closes the connection."""
        while True:
            command = await reader.readexactly(COMMAND_SIZE)
            connection.commands.append(command)
