# ADR-0004 — Server-Sent Events, not WebSocket, for realtime status

- **Status:** Accepted
- **Date:** 2026-07-29
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-fleet-manager.md`](../architecture/sentry-fleet-manager.md) §7.3

## Context

Requirements 1 and 6 demand realtime updates: the USB topology must live-reload as dongles are
plugged and unplugged, and per-SDR status must update continuously. The traffic profile is:

- **Strictly one-way.** Server → browser. Every client-initiated action (rename, set port, enable,
  flash a serial) is a discrete, idempotent-ish REST call that wants a status code and a body.
- **Low volume.** A handful of devices, a `health` frame every 5 s, and a `device_changed` on
  actual change — well under 1 KB/s at rest.
- **Small audience.** One or two browser tabs on a LAN, on a Raspberry Pi.

Note that Sentinel already uses a WebSocket (`/ws/sdr/{id}`) — but for a genuinely different job:
streaming binary spectrum frames with client→server tuning commands. That precedent does not
transfer.

## Decision

**Server-Sent Events** on `GET /api/events`, with named events (`snapshot`, `device_changed`,
`device_removed`, `health`, `notice`). Mutations stay on plain REST endpoints.

Design details that follow from the choice:

- The server sends `retry: 3000` and a full `snapshot` on every connect.
- `Last-Event-ID` is accepted and **deliberately ignored** — there is no replay buffer, and a
  fresh full snapshot on reconnect is strictly more correct than replaying a partial delta log.
- The `health` frame every 5 s doubles as the keepalive, so no bespoke ping/pong exists.
- Each subscriber has a bounded queue with drop-oldest; an overflow forces a `snapshot` on the
  next flush, so a slow client self-heals rather than drifting. (Deliberately the same discipline
  the relay already applies to IQ clients.)
- The client layers a 15 s stall detector on top of the native reconnect, to catch a proxy holding
  a dead-but-open stream — the one failure the browser's own reconnect misses.

## Consequences

**Positive**

- **The browser owns reconnection.** `EventSource` reconnects automatically with the server's
  `retry` interval. The equivalent WebSocket code — reconnect loop, exponential backoff, jitter,
  connection-state machine, heartbeat, heartbeat-timeout — is roughly 100 lines of frontend code
  that does not need to be written, tested or debugged.
- **It is plain HTTP.** Same origin, same port, same bearer-token middleware, same access logs,
  same `curl` debuggability (`curl -N http://pi:8000/api/events` prints the stream). A WebSocket
  needs a separate upgrade path, separate auth handling and a separate client to inspect.
- **Named events map directly onto the domain**, so the frontend registers one small handler per
  event type rather than switch-casing on a discriminator inside a single `onmessage`.
- Text framing suits the payload exactly — these are JSON status objects, not binary IQ.
- Trivially testable: an SSE endpoint is an async generator returning strings, asserted with
  `httpx`; the composable is tested against a mocked `EventSource`.

**Negative**

- **No client→server channel on the same connection.** Accepted, and in fact desirable: mutations
  belong on REST where they get status codes, validation errors and idempotency.
- **`EventSource` cannot set headers**, so bearer-token auth needs an `?access_token=` query
  parameter (mitigated by stripping query strings from access logs) or a cookie session. This is
  the one genuine cost and is raised for sign-off as open question §13.3.
- **The 6-connection-per-origin cap on HTTP/1.1.** Irrelevant here — one stream, one or two tabs,
  and the SPA is served from the same origin over HTTP/1.1 with only a handful of concurrent
  requests. Worth recording that it was considered.
- No binary frames. Not needed; nothing binary crosses this channel by design.

**Rejected alternatives**

- **WebSocket.** More capability than the problem has, at the cost of hand-written reconnection,
  heartbeating and a second auth path. Would be the right answer the moment Sentry needed to push
  spectrum data — it does not, and by design never will (that is Sentinel's job).
- **Polling `GET /api/status` every second.** Simplest of all, and genuinely tempting at this
  scale. Rejected because "live-reloading as dongles are plugged/unplugged" (requirement 1) wants
  sub-second feedback, and a 1 s poll either feels laggy or wastes the Pi's CPU re-serialising an
  unchanged fleet. SSE gives an event the moment udev fires.
- **Long-polling.** All of SSE's constraints with none of its browser support.
