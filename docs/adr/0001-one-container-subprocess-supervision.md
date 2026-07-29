# ADR-0001 — One container with subprocess supervision, not a container per dongle

- **Status:** Accepted
- **Date:** 2026-07-29
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-fleet-manager.md`](../architecture/sentry-fleet-manager.md)

## Context

Sentry must run N `rtl_tcp` + `rtl_tcp_relay.py` process pairs on a Raspberry Pi, where N changes
at runtime as dongles are plugged and unplugged. The existing stack runs exactly two containers
for exactly one dongle, declared statically in `docker-compose.yml`. Something has to create and
destroy those pairs dynamically.

Three options were considered.

**A. Container per dongle, orchestrated by the API via the Docker socket.** Sentry would call the
Docker Engine API to `create`/`start`/`stop` a `rtl-tcp-<id>` and `rtl-relay-<id>` container pair
per device.

**B. One container, subprocesses supervised in-process.** A supervisor task inside the FastAPI
process spawns and watches an `rtl_tcp` + relay pair per enabled device.

**C. One container, an external supervisor (s6-overlay / supervisord) driven by generated config.**
Sentry would write config files and signal the supervisor to reload.

## Decision

**Option B.** One container. A supervisor asyncio task inside the API process spawns one
`rtl_tcp` and one `rtl_tcp_relay.py` **OS subprocess** per enabled device, watches both, and
restarts the pair on any exit with a capped backoff and a restart budget.

The relays are real subprocesses, not asyncio tasks inside the API. This is not negotiable: each
relay moves roughly 4 MB/s of IQ, which must not contend with the HTTP/SSE event loop, and a
relay crash must not take the API down with it. The supervisor spawns, waits, and kills — it
never touches an IQ byte.

## Consequences

**Positive**

- The Docker socket mount can be deleted entirely (ADR-0002), removing a root-equivalent host
  capability from a network-facing service.
- The supervisor is the pair's **parent process**, so it observes exit codes directly and can
  distinguish "crashed", "wedged" (exit 75) and "stopped by us" without polling an external API.
- Kill-and-respawn is strictly stronger recovery than the old container restart: a wedged
  `rtl_tcp` is replaced along with its relay, rather than the relay merely being reconnected.
- Dramatically more testable. `ProcessSpawner` is a two-method Protocol, so the entire supervisor
  — spawn argv, env, slot allocation, restart budget, backoff schedule, shutdown escalation — is
  unit-tested against a fake on a laptop. The Docker-API equivalent would require either a live
  daemon or an elaborate HTTP mock of the Engine API.
- One image to build, one container to start, one log stream, one thing to restart. On a headless
  Pi that an operator rarely shells into, that matters.
- No dependency on a specific container runtime, so the same code runs bare-metal under systemd.

**Negative**

- Loss of per-dongle kernel-level resource isolation. A pathological `rtl_tcp` shares the
  container's cgroup with the API. Mitigation: the supervisor's restart budget bounds the damage,
  and the API and relays are separate processes so a relay cannot corrupt API state.
- The container needs `privileged: true` (or the equivalent device rules) for the whole USB bus,
  which it already needed. Nothing is worse here; nothing is better either.
- The supervisor is now Sentry's most safety-critical code, so it carries the heaviest test
  burden in the project (§12.7 of the spec).
- Restarting the container restarts every dongle. Accepted: this is a single-purpose appliance,
  and per-device restart is available through the API without touching the container.

**Rejected alternatives**

- **A (container per dongle)** — requires the Docker socket, which is root-equivalent on the host
  and is exactly what ADR-0002 removes. It also makes the API responsible for image lifecycle,
  container naming collisions and orphan cleanup after an unclean shutdown, and it is close to
  untestable without a live daemon.
- **C (s6/supervisord)** — adds a second configuration language and a second failure surface, and
  crucially makes the API's view of process state *indirect*: to know why a pair died, Sentry
  would have to parse another supervisor's logs. Given the wedge-detection requirement depends on
  reading a specific exit code, direct parenthood is worth far more than the reload machinery it
  would save.
