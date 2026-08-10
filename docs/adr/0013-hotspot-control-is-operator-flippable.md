# ADR-0013 — Hotspot control moves from `.env` to a console switch

- **Status:** Accepted
- **Date:** 2026-08-10
- **Deciders:** project owner
- **Amends:** [ADR-0007](0007-nmcli-over-host-dbus-for-the-hotspot.md) (mitigation 1)
- **Builds on:** [ADR-0010](0010-sentinel-reads-sentry-manages.md) (the console password this relies on)

## Context

ADR-0007 gated the entire hotspot surface behind `SENTRY_HOTSPOT_CONTROL_ENABLED`,
defaulting false, and was explicit about why:

> The entire mutating surface is opt-in at deploy time, in `.env`, by someone
> with shell access to the Pi.

Shell access was the trust anchor. At the time it was the only one available:
ADR-0007 predates the console password, and the alternative was an API token
that an operator had to paste into a browser every session.

What that produced in practice is a console that fully manages a feature it
cannot turn on. The UI's own instructions were a shell command to copy —
`echo 'SENTRY_HOTSPOT_CONTROL_ENABLED=true' >> .env && docker compose up -d` —
with a copy button next to them. The instructions had become the product.

Three things have changed since:

- **ADR-0010 introduced a console password.** There is now an authentication
  mechanism that ADR-0007 did not have.
- **The hotspot routes already require it.** `_require_console_password` refuses
  every hotspot mutation while no password is set. "Hotspot changes need a
  password" is established behaviour, not something invented here.
- **The container already has the capability.** `docker-compose.yml` mounts
  `/run/dbus/system_bus_socket` unconditionally and runs `privileged: true` with
  `network_mode: host`. The D-Bus socket was never the gate; a boolean read once
  at startup was.

## Decision

**Hotspot control is a switch in the console, stored in the database, and the
console password is what protects it.**

- `host_control_settings.hotspot_control_enabled` (migration 0005, single row)
  holds the switch. It defaults **false**, exactly as the environment variable
  always did — what changed is who can flip it, not what a fresh install does.
- `PUT /api/hotspot/control` flips it, and **refuses with `409` while no console
  password is set**. A refusal, not a hidden control: this is the one route that
  can *grant* the capability every other hotspot route guards.
- **`SENTRY_HOTSPOT_CONTROL_ENABLED` still works, and still wins.** It can only
  enable, never disable. An operator who set it is depending on it, and a UI
  toggle silently overriding a deploy-time decision would defeat the point of
  having one. The API reports `forced_by_environment` so the UI can explain a
  switch that will not move.
- The switch is applied **per call**, by `GatedWifiApController`, not once at
  startup — because the answer can now change while the process runs.

### What is preserved

ADR-0007's central property is unchanged: **with control switched off, nothing
reaches nmcli or the D-Bus socket.** That is why the gate is a delegating
controller rather than a boolean inside `NmcliWifiApController` — a flag checked
inside the real adapter would put the enforcement one layer deeper than the
capability, which is the wrong way round. A Sentry with the switch off executes
no `nmcli` and makes no D-Bus call, exactly as before.

ADR-0007's mitigations 2, 3 and 4 are untouched.

## Consequences

**Good.**

- The console can turn on a feature it already fully manages. No terminal, no
  container recreation, no copy-button instructions.
- It removes a documented trap. The correct command is `up -d`, not `restart` —
  `restart` reuses the existing container and its original environment, so the
  change appears not to have worked. That already cost this project an hour of
  debugging on a real Pi, and the shape of the mistake was entirely predictable.
- Stale copy went with it. Two messages still told operators to set
  `SENTRY_AUTH_TOKEN`, deleted by ADR-0010 — instructions to add a line that
  does nothing.

**Bad, and accepted.**

- **The trust anchor is weaker.** "Has SSH access to the Pi" is a higher bar
  than "can reach the console and knows the password". Anyone who can sign in
  can now switch on host network control, where previously they could not
  without a shell.
- **It is only as strong as the console password.** ADR-0010 makes that password
  optional, and a fresh install has none. The `409` is what closes that gap —
  an open console cannot flip this switch at all — but it means the protection
  is a check in a route rather than a property of the deployment. A bug there
  is a bug in the gate itself.
- **A restart is no longer proof of intent.** Previously, enabling required a
  deliberate act on the host that left a trace in `.env`. Now it is a click, and
  the only record is `host_control_settings.updated_at`.

## Alternatives considered

**Leave it in `.env`.** Rejected as the status quo whose cost is a copy-command
in the UI. Defensible only while there was no authentication to replace shell
access with; ADR-0010 removed that constraint.

**Write `.env` from the container, leaving the operator only `docker compose
up -d`.** Rejected as half a fix that keeps the terminal step and adds
file-mounting complexity, while the restart trap survives intact. It also leaves
the container writing a file whose whole purpose is to be outside its control.

**Toggle it, but keep `.env` authoritative on conflict.** This is what was
built — the environment variable wins — so this is less an alternative than the
resolution of one. The rejected version was making `.env` able to *disable* a
console-enabled switch, which would produce a toggle that flips, persists, and
does nothing.

**Hide the toggle when no password is set, rather than refusing it.** Rejected:
hidden reads as "not available on this Pi", which is untrue and unactionable.
Disabled, next to the reason, reads as "do this first". The API refuses either
way — the UI state is presentation, never the enforcement.
