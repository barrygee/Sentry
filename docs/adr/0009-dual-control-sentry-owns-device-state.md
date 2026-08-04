# ADR-0009 — Dual control: Sentry owns device state, Sentinel is a remote client

- **Status:** Accepted
- **Date:** 2026-08-04
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-sdr-controller.md`](../architecture/sentry-sdr-controller.md)
- **Related:** [ADR-0008](0008-static-ui-over-vue-spa.md) (the console this leaves behind)

## Context

Until now the two apps met at exactly one seam: `GET /api/v1/sdrs`, a pull-only
export Sentinel does not even consume. An operator configured devices in Sentry's
own UI, then typed an IP and a port into Sentinel's SDR form by hand. Sentinel had
no idea Sentry existed.

The project owner's goal was to manage all of it from Sentinel — naming, port
assignment, public/private, WiFi, and live plug/unplug — so that a new feature is
built once rather than twice.

The obvious reading of "once rather than twice" is to move the state into
Sentinel and reduce Sentry to a thin executor that is told what to run. That was
the original plan. It was rejected once a second requirement landed: **Sentry
keeps a working UI**. A Pi whose console only works when Sentinel can reach it is
useless in precisely the situation you need a local console — the WiFi is
misconfigured and the network is the problem.

With two UIs that can both write, "who owns the state?" stops being a detail.

## Decision

**Sentry remains the source of truth for device configuration. Sentinel is a full
remote client of Sentry's existing HTTP API.**

Concretely:

- Sentry keeps its `sdr_devices` table and every column in it — name, port,
  visibility, notes, antenna, enabled, tuning. No migration, no columns moved.
- Sentry keeps the rules that go with owning that state: name uniqueness, the
  port allocator's six validation rules and its bind probe, identity resolution,
  the supervisor, EEPROM flashing, and the hotspot.
- Sentinel stores only what is genuinely its own — which Sentry hosts it knows,
  and a **cache** of their devices — and writes through to Sentry's API for
  anything else.
- Both UIs are peers over the same routes. Neither is privileged.

The management API (`/api/status`, `/api/devices`, `PATCH /api/devices/{id}`,
`POST /api/devices/{id}/serial`, the `/api/hotspot/*` set) therefore stops being
an internal UI API and becomes **a contract with an independently-deployed second
party**. It is versioned accordingly: `X-Sentry-Api-Version`, a single integer
bumped only on a breaking change, stamped on every `/api` response including
errors (`app/backend/api_version.py`). `GET /api/v1/sdrs` keeps its own separate
`X-Sentry-Sdr-Api-Version` — a breaking change to device configuration has no
bearing on the published SDR list, and versioning them together would force
false bumps on both.

## Consequences

**Good.**

- No split-brain. There is one writer of record, so there is no reconciliation
  logic, no last-write-wins, and no class of bug where the two apps disagree
  about a port.
- No duplicated model. Sentinel does not reimplement port validation or name
  uniqueness; it calls Sentry's and surfaces the rejection codes verbatim.
- Sentry's UI keeps working with Sentinel switched off, which was the point.
- Far less work than the desired-state design it replaces: no new Sentry API, no
  migration, no port allocator in Sentinel.

**Bad, and accepted.**

- **A device feature now has three surfaces**: Sentry's API, Sentry's UI, and
  Sentinel's UI — the literal inverse of the "build it once" goal that started
  this. The mitigation is not technical but a standing rule: **Sentry's UI is
  frozen at its current feature set.** It reached parity in ADR-0008 and stops
  there; everything new goes to Sentinel only. If that discipline slips, this
  decision starts costing what it was meant to save.
- Sentinel's device list is a cache, so it can be stale. It is refreshed by a
  2-second poll per host, and every write goes to Sentry and re-reads, but a
  Sentinel window left open on a dead network will show old data until the poll
  fails. Connection state is surfaced in the UI for exactly this reason.
- Sentry's API is now load-bearing for a client it cannot see deploy. Breaking
  changes need the version bump and a real deprecation path, where previously
  the SPA shipped in the same image and could simply be changed in step.

## Alternatives considered

**Sentinel owns the state; Sentry's UI writes back to Sentinel.** Rejected: it
satisfies "one place" literally but makes Sentry's console useless exactly when
it is needed, which defeats the reason for keeping it.

**Two-way sync with revisions and conflict detection.** Rejected as unjustified
complexity. It buys offline editing on both sides, which nobody asked for, at the
cost of the hardest category of bug to diagnose.

**Sentry as a thin desired-state executor** (the original plan: Sentinel pushes
`PUT /api/desired-state`, Sentry reconciles). Rejected once Sentry kept its UI —
a thin executor has no state for a local console to edit, so the console would
have had nothing to show.
