# ADR-0003 — Three-tier device identity; librtlsdr index resolved at spawn, never cached

- **Status:** Accepted
- **Date:** 2026-07-29
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-sdr-controller.md`](../architecture/sentry-sdr-controller.md) §5

## Context

Sentry must attach a persistent name, output port and tuning to a *physical dongle*, and that
binding must survive reboots, replugs and hub rewiring (requirement 7). This is unexpectedly hard
for RTL-SDR hardware:

- **Factory serials are not unique.** The overwhelming majority of cheap RTL-SDR dongles ship
  with `00000001`. A user with three dongles typically has three identical serials.
- **The librtlsdr device index is not stable.** `rtl_tcp -d <index>` addresses devices by
  enumeration order, which depends on USB probe order and changes across reboots, replugs, and
  even hub power-cycles. An index cached at configuration time will, sooner or later, point at
  the wrong dongle.
- **The kernel `devnum` is not stable either** — it increments on every re-enumeration (the
  existing README documents a device going 3 → 4 in `dmesg`).
- **Dongles sit behind hubs and USB extenders** (requirement 4), so "which physical Pi port" is
  not a single number.

Getting this wrong has a specific, bad failure mode: after a reboot, the operator's "ADSB SDR"
configuration silently applies to their AIS dongle, and both feeds are quietly wrong. Silently
wrong is far worse than visibly unconfigured.

## Decision

Separate the two jobs identity is being asked to do, and never conflate them.

### 1. Persistence key — three tiers, with a refusal at the bottom

| Tier | Key | Chosen when |
|---|---|---|
| 1 | `serial:<value>` | The serial is non-empty, not in the known-default set (`00000001`, `00000000`, `0000001`, blank), **and** unique among all currently present devices |
| 2 | `usb:<topology_path>` e.g. `usb:1-1.4.2` | Tier 1 unavailable but the sysfs topology path is unambiguous |
| 3 | *none* — **"needs identification"** | Two present devices collapse to the same key, or sysfs data is incomplete |

The topology path is read from sysfs and has exactly the property required: `1-1.4.2` means "bus
1, root port 1, hub port 4, hub port 2". **It encodes the hub tree**, so USB extenders and
multi-port hubs work naturally, with no special cases and no separate hub model.

Tier 3 is a **refusal, not a fallback**. A tier-3 device gets no persisted row, no spawned
process pair, and a UI prompt to flash a unique serial. Sentry never guesses.

Tier promotion (`usb:` → `serial:` after a flash) preserves the record. Demotion is refused, so a
firmware glitch cannot orphan a configuration.

### 2. Spawn address — resolved every time, cached never

At every spawn, the supervisor calls `rtlsdr_get_device_count()` and
`rtlsdr_get_device_usb_strings(i)` via ctypes and matches on `(serial, manufacturer, product)` to
find the index *for this instant*. Ambiguity is an error state, never a coin toss:

| Situation | Result |
|---|---|
| Exactly one match | Spawn `rtl_tcp -d <index>` |
| No match | `state: error`, `state_reason: index_unresolved` |
| Multiple matches | `state: error`, `state_reason: ambiguous_index` — UI offers serial flashing |
| `device_count() == 0` while sysfs shows a device | `state: error`, `state_reason: driver_conflict` — the DVB kernel module is bound; the message names the blacklist fix |

### 3. Serial flashing is in scope

`rtl_eeprom -s <serial>` is exposed through a guarded endpoint so the operator can convert a
tier-2/tier-3 set of SDRs into a tier-1 set permanently. Guards: device must be idle, explicit
`confirm: true`, strict `^[A-Za-z0-9_-]{1,32}$` allow-list, collision check, per-device lock, and
`exec` with a **list argv, never a shell string**.

## Consequences

**Positive**

- The common case (one flashed serial per dongle) is rock solid across reboots and any replug.
- The awkward case (three identical `00000001` dongles) still works out of the box via topology,
  and the UI offers a permanent fix rather than living with it.
- The dangerous case is impossible: Sentry never silently binds a saved name to the wrong radio.
- USB extenders and hubs need no special handling at all — the topology path already models them.
- `identity.resolve(snapshots)` is a **pure function over the whole snapshot set** (uniqueness is a
  set-wide property, so it cannot be decided per-device). It is exhaustively unit-testable and is
  the single highest-value test target in the project.
- Resolving the index at spawn means a re-enumeration between two spawns is simply handled — the
  next spawn asks again.

**Negative**

- Tier-2 devices lose their identity if the operator rearranges the hub wiring. This is inherent
  to positional identity and is honest: the device reappears as newly `detected`, and the stale
  row is shown as absent rather than silently rebound. The UI nudges toward flashing a serial.
- Serial flashing is a genuinely destructive hardware operation exposed over HTTP. It carries the
  heaviest guard set in the codebase and the most negative tests (§12.10), and it is the primary
  reason `SENTRY_AUTH_TOKEN` exists as an option.
- A ctypes dependency on `librtlsdr` is added to the API process. Confined to one adapter behind
  the `RtlSdrLibrary` Protocol; only the `CDLL` load itself is untestable.
- Two identity kinds means two code paths in the registry (migration, absence handling). Bounded,
  and the alternative — one weaker key — is what causes the silent-misbinding failure.

**Rejected alternatives**

- **Index only.** Trivial and wrong; breaks on the first reboot.
- **Serial only.** Would leave the majority of real deployments permanently unconfigurable, since most
  dongles ship with the same serial.
- **Topology only.** Loses the strongest available identity, and makes a dongle moved between two
  ports look like a new device even when it self-identifies perfectly well.
- **Silently disambiguating duplicates by enumeration order.** Rejected outright: it produces a
  system that appears to work and is intermittently, invisibly wrong.
