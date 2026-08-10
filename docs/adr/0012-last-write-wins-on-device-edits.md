# ADR-0012 — Local drafts win on device edits; no conflict detection

- **Status:** Accepted
- **Date:** 2026-08-10
- **Deciders:** project owner
- **Relates to:** [ADR-0010](0010-sentinel-reads-sentry-manages.md) (Sentinel reads, Sentry manages), [ADR-0004](0004-sse-over-websocket.md) (SSE delivers changes)

## Context

Device cards used to save each field the moment it lost focus. That made the
window between reading a value and writing it a few milliseconds wide, so two
browsers editing the same device essentially could not collide — not by design,
but as a side effect of never holding an unsaved value for long.

Saving now happens on an explicit button press. A card can hold unsaved drafts
for minutes, which opens a window that did not previously exist: the server can
change underneath an operator who is mid-edit.

Two things already in place matter here:

- **Changes already arrive.** `device_changed` over SSE (ADR-0004) reaches every
  open browser within about a second, and the card re-renders on it. Browser B
  is *told* about browser A's edit; it simply loses to a local draft.
- **A version stamp already exists.** `SdrDevice.updated_at` is on the row and
  on `DeviceRecord`. Optimistic concurrency would need no migration — only
  exposure through `DeviceStatus` and a check in `PATCH /api/devices/{id}`.

So the missing piece is not plumbing. It is that the UI has no concept of "this
changed underneath me", because until now there were no drafts for it to apply
to.

## Decision

**Local drafts win, silently. Concurrent edits are not detected, and the
operator is not told when one is overwritten.**

- While a card has unsaved edits, incoming server values for *any* field on that
  card are ignored until the operator saves or discards.
- Saving sends only the fields that differ from the last-seen device, so an open
  card does not write back values it merely happened to be displaying. This
  narrows the blast radius to fields actually edited — it does not eliminate it.
- A card with no unsaved edits follows the server normally. "Dirty" is tracked
  as an explicit flag, not inferred by comparing drafts to the device: that
  comparison cannot distinguish an edit made here from a rename arriving from
  Sentinel, and treating the second as dirty would freeze the card against the
  server permanently.

This is a decision about **one operator**. Sentry today is a single-user
appliance on a home LAN, and Sentinel reads but does not write (ADR-0010). A
conflict notice on a device only one person edits is noise on every save,
warning about something that cannot happen.

## Consequences

**Good.**

- Edits cannot be lost by a background refresh, which is the failure that was
  actually reported and observed — a note typed and then wiped by the
  five-second `health` tick. That is a real bug affecting one operator; conflict
  loss is a hypothetical affecting two.
- No conflict UI to design, explain, or maintain, and no code path that real use
  never exercises.

**Bad, and accepted.**

- **A concurrent edit is lost with no trace.** If a second browser changes a
  field while a card sits open with unsaved edits, saving overwrites it and
  nobody is told — not the person who made the lost change, not the person who
  overwrote it.
- **The window is unbounded.** A card left open with unsaved edits ignores
  server changes for as long as it stays open — minutes or hours, not the few
  milliseconds the previous design implied.
- **The failure is invisible in exactly the case it matters.** The overwriting
  operator sees a successful save. Nothing distinguishes it from an uncontested
  one.

## When to revisit

This ADR should be superseded when any of these becomes true — each makes the
overwrite reachable rather than theoretical:

- **A Sentinel instance gains write access.** ADR-0010 confines Sentinel to
  reads, and that is the main reason this is safe today.
- **A second person edits the same Sentry**, including the same person on a
  phone and a laptop at once.
- **Any automated writer** — a script, a scheduled job — starts patching devices.

## Alternatives considered

**Show a conflict notice, still let local drafts win** (roughly an hour's work,
frontend only). The card already re-renders on `device_changed`; it would
compare incoming values against the fields with unsaved drafts and add a line to
the Save row — "Antenna was changed elsewhere". Rejected as premature rather than
wrong: it is the right first step, and it is the one to reach for when the
revisit conditions above are met. Building it now would ship a branch that never
executes.

**Optimistic concurrency — reject stale saves** (roughly half a day). The card
holds the `updated_at` it last saw, `PATCH` carries it, the server returns `409`
if the row has moved on. This makes silent overwrites *impossible* rather than
merely visible, and needs no migration. Rejected for now on the same grounds,
with one caveat worth recording: the server-side half could be added alone, with
no conflict UI at all, and would act as a guard rail against data loss even if
nobody ever saw the error. That remains the cheapest meaningful hardening if the
appetite for it appears before a second writer does.

**Per-field merge** — reconcile field by field, keeping both sides where they do
not collide. Rejected as disproportionate: four editable fields, one operator,
and a merge UI is harder to understand than the loss it prevents.

**Keep saving on blur.** Rejected as the cause of the reported bug. It made
conflicts rare by making every edit an immediate write, which also meant a
half-finished card was persisted keystroke by keystroke, and a first
configuration could not be expressed at all — name and port must be sent
together on a device with no row.
