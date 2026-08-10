# ADR-0007 — Drive the host's NetworkManager over the system D-Bus socket, not a privileged sidecar

- **Status:** Accepted
- **Date:** 2026-08-04
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-sdr-controller.md`](../architecture/sentry-sdr-controller.md)

## Context

Sentry serves each dongle as an `rtl_tcp` endpoint on the LAN. A Sentinel operator reaches it by
typing an IP and a port into Sentinel's own settings form — Sentinel has no discovery mechanism and
does not consume `GET /api/v1/sdrs`. That works only where a LAN already exists. In a vehicle, in a
field, or anywhere Sentry is carried to, there is nothing for either machine to join.

So Sentry should raise its own WiFi network and let clients join that directly. The network must be
**hidden by default**, so joining requires knowing the SSID and passphrase in advance, and the whole
thing must be configurable from Sentry's own web UI.

The target host is Raspberry Pi OS Bookworm, whose default network stack is **NetworkManager**. NM
can raise a WPA2/WPA3 access point with a suppressed SSID and, with `ipv4.method shared`, supply
DHCP, DNS and NAT itself — so nothing has to hand-roll `hostapd` and `dnsmasq` configuration or
fight NM for control of the radio.

`nmcli` is a D-Bus client. For a process inside Sentry's container to drive the host's
NetworkManager, the container needs the host's system bus socket.

That runs directly into **ADR-0002**, which deleted the `/var/run/docker.sock` mount on the grounds
that "combining a LAN-facing API with a root-equivalent host capability in one container is an
unacceptable escalation path", and which rejected a narrow privileged sidecar as unjustified
complexity.

Two options were considered.

**A. Mount `/run/dbus/system_bus_socket` and run `nmcli` inside the existing container.**

**B. A host-side systemd helper daemon**, shipped in this repo, exposing a narrow Unix-socket JSON
API with only the access-point operations, with that socket mounted into the container.

## Decision

**Option A.** Mount the host's system D-Bus socket read-write, install `network-manager` in the
runtime image for `/usr/bin/nmcli` alone (its bundled daemon is never started — there is no init in
this container), and drive exactly one NM connection profile, `sentry-hotspot`, through the existing
`ProcessSpawner` seam. That profile is the **sole system of record**: no new database table and no
Alembic migration is added, and NM keeps the pre-shared key in its own root-only keyfile rather than
in Sentry's SQLite.

**On the ADR-0002 question.** The escalation objection does not apply, but not for the obvious
reason. `docker-compose.yml` already sets `privileged: true` and `network_mode: host`, and the image
already runs as root — a process in this container can mount the SD card and `insmod` a module
today. The D-Bus socket is a strict *subset* of capability it already holds, so it adds no new
escalation path.

What *is* genuinely new is that the LAN-facing HTTP API gains a route that reconfigures host
networking. That risk is **identical under option B**: a helper daemon is triggered by the same
LAN-facing FastAPI process, reachable by the same callers. It moves the code, not the exposure —
while costing a second deployment artefact installed outside Docker, a bespoke IPC protocol and
socket-permissions model, a version skew between daemon and container, and a broken
`docker compose up` quick start. That is the shape ADR-0002 itself rejected, here without the
offsetting isolation benefit.

The mitigation is therefore **gating the capability, not isolating the transport**:

1. `SENTRY_HOTSPOT_CONTROL_ENABLED` defaults **false**. The entire mutating surface is opt-in at
   deploy time, in `.env`, by someone with shell access to the Pi.
   **Amended by [ADR-0013](0013-hotspot-control-is-operator-flippable.md):** the switch moved into
   the console, protected by the console password rather than by shell access. The variable still
   works and still wins, and the property that a switched-off Sentry executes no `nmcli` and makes
   no D-Bus call is unchanged. Mitigations 2-4 below are untouched. A stock `docker compose up`
   cannot touch host networking, executes no `nmcli`, and makes no D-Bus call.
2. `SENTRY_HOTSPOT_REQUIRE_AUTH_TOKEN` defaults **true**. With control enabled and
   `SENTRY_AUTH_TOKEN` unset, every mutating route refuses with `409 auth_token_required`,
   `GET /api/hotspot` reports `warnings: ["auth_token_missing"]`, the UI blocks the form, and startup
   logs a warning. This is a hard refusal rather than advice, because an access point puts anyone in
   radio range who has the passphrase one join away from an API that spawns processes and writes
   dongle firmware.
3. Sentry owns exactly one profile and never reads, edits or deletes any other. There is no "list the
   host's networks" surface.
4. **No passphrase-reveal endpoint, ever.** Retrieving a stored key requires `nmcli --show-secrets`,
   which would place the highest-value secret on the box into a subprocess buffer, an HTTP body, the
   browser's DOM, and any intermediary's logs — four places it does not currently exist. Recovery
   from a forgotten passphrase is "set a new one", costing joined clients one reconnect. Disclosure
   is not reversible. `nmcli` is never invoked with `-s`, and that absence carries a code comment
   saying it is a control rather than an oversight.

**The feature is strictly additive.** `_resolve_host`, the `GET /api/v1/sdrs` contract,
`_PUBLIC_EVENT_NAMES`, the `rtl_tcp`/relay wire contract and the `sdr_devices` schema are all
untouched, and the Sentinel repository is not modified at all. Hotspot outcomes ride the existing
`notice` SSE event rather than introducing a new event name.

## Consequences

**Positive**

- No new escalation path: a strict subset of capability the container already holds.
- One container, one artefact, one `docker compose up`. ADR-0001's posture is intact.
- NetworkManager owns DHCP, DNS, NAT and regulatory handling, so none of that is reimplemented, and
  an operator can inspect and repair the result with ordinary `nmcli` on the Pi.
- The configuration survives a reboot without Sentry running, because NM holds it.
- Every command is a fully-formed argv through `ProcessSpawner`, which already has a fake — so the
  entire flow, including the rollback timer, is testable with no radio, no NetworkManager and no
  root.
- Injection is structurally impossible rather than filtered: `AsyncioProcessSpawner` uses
  `create_subprocess_exec`, so there is no shell for a metacharacter to mean anything to.

**Negative**

- The LAN-facing API gains the ability to reconfigure host networking. Mitigated by the two gates
  above, not by isolation. Said plainly rather than implied away.
- The passphrase transits `nmcli`'s argv and is therefore briefly visible in `/proc/<pid>/cmdline`,
  which is root-only on a host this container is already root on. Accepted for this version; writing
  the NM keyfile directly is the documented future hardening.
- `ipv4.method shared` makes NM install masquerade and forward rules, so a joined hotspot client can
  route to the Pi's uplink LAN. That is inherent to getting DHCP, DNS and NAT for free, and is
  standard NM hotspot behaviour. Documented, not prevented.
- Sentry now depends on the host running NetworkManager with `dnsmasq-base`. A host using `dhcpcd` or
  `systemd-networkd` degrades to a read-only `available: false` rather than failing.
- On a single-radio Pi, raising the access point on the interface that carries the uplink drops that
  connection. This is physics, not a design choice, so the design refuses to do it silently:
  interface selection never auto-picks an interface with an active connection or the default route;
  doing so anyway requires explicit confirmation; and a commit-confirm rollback timer restores the
  previous connection unless someone proves they can still reach the API. The in-process nature of
  that timer is itself a stated bound — a restart inside the confirmation window leaves the hotspot
  up but with `autoconnect` off, so it survives until reboot and not past one.
- **A hidden SSID is not a security control.** It defeats casual scanning and nothing more; the
  network is still discoverable by anyone watching a client associate. The pre-shared key is what
  protects it. The README says so where an operator will read it.
- There is no rate limiting on these routes, because this codebase has none anywhere and adding a
  general mechanism is out of scope. The concrete bounds are a single service lock that fast-fails
  with `409 hotspot_busy`, a per-command timeout with a kill, and authentication.

## Rejected alternatives

- **A host-side systemd helper daemon with a narrow Unix-socket API (option B).** Real code
  isolation, zero risk reduction — the LAN-facing API still holds the trigger — plus a second
  artefact, a bespoke protocol, version skew and a broken quick start. Rejected for the same reason
  ADR-0002 rejected its sidecar.
- **Ship and supervise `hostapd` + `dnsmasq` inside the container.** Fights NetworkManager for
  `wlan0`, duplicates its DHCP, NAT and regulatory-domain handling, and breaks the moment NM reclaims
  the device. Rejected.
- **Speak D-Bus natively from Python (`sdbus`, `dbus-fast`).** Avoids one apt package and the argv
  exposure of the passphrase, at the cost of reimplementing a large slice of NetworkManager's API
  with no `nmcli` to debug against on the Pi. Rejected for this version; revisit if the argv exposure
  becomes unacceptable.
- **`nmcli device wifi hotspot`, the one-liner.** Convenient, but it does not let the AP-side address
  be pinned — and that address is exactly what a human types into Sentinel by hand, so it must never
  move between activations. Rejected.
- **A `hotspot_config` table plus a migration.** Two sources of truth that can silently drift from
  what the radio is actually doing. Rejected: NetworkManager's profile is authoritative, and Sentry
  reads it back rather than remembering it.
