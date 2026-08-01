# ADR-0002 — Drop the Docker socket; recover a wedged dongle by process exit

- **Status:** Accepted
- **Date:** 2026-07-29
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-fleet-manager.md`](../architecture/sentry-fleet-manager.md) §2.1

## Context

An RTL-SDR dongle can survive a USB re-enumeration as a **live process that accepts connections
but never streams** — the classic "wedged but not exited" state. Docker's `restart: unless-stopped`
cannot catch it because `rtl_tcp` never dies.

The current relay solves this with `UpstreamWatchdog`: after N consecutive no-data cycles it
opens `/var/run/docker.sock` and issues `POST /containers/rtl-tcp/restart`. This works, and the
existing README is honest about the cost:

> The relay mounts `/var/run/docker.sock` so its watchdog can restart `rtl-tcp` on a silent-dongle
> wedge. This grants the relay container root-equivalent host control.

Access to the Docker socket is equivalent to root on the host: any process holding it can start a
privileged container mounting `/`. In the single-dongle stack the socket was held by a process
that only ever spoke to `127.0.0.1`. In Sentry, the same container additionally runs a
**network-facing HTTP API** that accepts operator input and can execute `rtl_eeprom`. Combining a
LAN-facing API with a root-equivalent host capability in one container is an unacceptable
escalation path, and one that exists purely to work around not being the process's parent.

## Decision

**Delete the `/var/run/docker.sock` mount and `RELAY_RESTART_CONTAINER` from the deployment.**

Because Sentry's supervisor is the pair's parent process (ADR-0001), wedge recovery becomes an
exit code. `UpstreamWatchdog` gains one additive branch:

```
RELAY_EXIT_ON_WEDGE   = "1" | ""  (default "")
RELAY_WEDGE_EXIT_CODE = int       (default 75)
```

When `RELAY_EXIT_ON_WEDGE` is set, a sustained wedge makes the relay log and `os._exit(75)`
instead of calling Docker. The supervisor sees exit 75, raises a `notice`, and kills and respawns
**both** processes in the pair.

> **Amended.** The Docker-restart branch was initially left in place so the retained legacy
> single-dongle compose kept working. That compose has since been removed from the repository,
> which left the branch with no consumer at all — so `_restart_container` and its
> `RELAY_RESTART_CONTAINER` / `RELAY_DOCKER_SOCK` settings were deleted as well. Process exit is
> now the watchdog's only recovery mechanism.

## Consequences

**Positive**

- A root-equivalent host capability is removed from a network-facing service. This is the single
  largest security improvement in the Sentry work.
- Recovery is **stronger**, not merely equivalent. The old path restarted the `rtl-tcp` container
  and left the relay to reconnect; the new path replaces the wedged `rtl_tcp` *and* its relay,
  clearing any half-open USB handle on both sides.
- Recovery is **faster** — a fork/exec versus a container stop/start cycle on a Pi.
- Recovery is **scoped**. One wedged dongle no longer requires restarting a container; the other
  dongles keep streaming, untouched. Under the old model with N dongles in one container, a single
  wedge would have restarted the whole fleet.
- The relay's dependency on Docker disappears entirely, so it runs identically under systemd,
  under Docker, or straight from a shell in a test.
- The exit-75 branch is trivially testable: the fake `rtl_tcp` has a `wedge` mode that accepts
  connections and never streams, and the supervisor's response is asserted against
  `FakeProcessSpawner`. The Docker path never had an equivalent test.

**Negative**

- The relay now terminates itself on a condition it previously survived. If Sentry's supervisor
  were ever *not* the parent — someone running the relay by hand with `RELAY_EXIT_ON_WEDGE=1` —
  the relay would exit and stay dead. Mitigated by the flag defaulting off and by the README
  documenting that it is a supervised-only setting.
- A wedge now costs downstream consumers a full reconnect (the relay's listening socket closes),
  whereas the old path could sometimes recover with the relay's socket intact. In practice the
  IQ stream was already dead at that point, and every real consumer — including Sentinel —
  reconnects automatically. Accepted.
- The restart budget must bound this: a genuinely broken dongle would otherwise exit-75 in a loop.
  Handled by the supervisor's 5-restarts-in-120s budget → `state: error` with capped backoff.

**Rejected alternatives**

- **Keep the socket, mount it read-only.** `:ro` on a Unix socket does not restrict the API calls
  made through it — it is security theatre. Rejected.
- **A separate tiny privileged sidecar holding the socket, with a narrow "restart X" API.** Real
  isolation, but it reintroduces a second container and a bespoke IPC protocol to avoid something
  the parent process gets for free. Rejected as unjustified complexity.
- **Have the supervisor detect the wedge itself** (e.g. by probing the relay's IQ port for data).
  Rejected: the relay already has the correct, battle-tested detection logic sitting exactly where
  the data is. Duplicating it in the supervisor would mean two implementations disagreeing.
