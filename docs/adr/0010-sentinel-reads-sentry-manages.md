# ADR-0010 — Sentinel reads, Sentry manages; a console password replaces the API token

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** project owner
- **Supersedes:** [ADR-0009](0009-dual-control-sentry-owns-device-state.md)
- **Related:** [ADR-0008](0008-static-ui-over-vue-spa.md) (the console this un-freezes),
  [ADR-0007](0007-nmcli-over-host-dbus-for-the-hotspot.md) (the deploy-time gates that remain)

## Context

ADR-0009 made Sentinel a **full remote client** of Sentry's management API:
naming, port assignment, visibility, WiFi and live plug/unplug, all driven from
Sentinel, with Sentry keeping a local console as a fallback. It accepted, in
writing, that a device feature would then have three surfaces — Sentry's API,
Sentry's UI, Sentinel's UI — and mitigated that with a standing rule that
Sentry's UI was frozen at its current feature set.

Five days of using it did not bear that out. The console did not behave like a
fallback: it is where devices actually get managed, and the freeze was brushed
against twice in a single session — a notice-attribution fix, then a navigation
restructure — with a straight face each time. A rule broken that readily on its
first contact with real use is not a rule; it is a note about what someone once
intended.

The authentication design pushed the same way. `SENTRY_AUTH_TOKEN` guards the
whole API with one shared bearer token, which exists in that shape largely
*because* Sentinel needed a machine credential it could send on every write. In
practice the token is pasted into a browser once per tab session, shared by
copying it to whoever else needs access, and grants everyone identical total
control. The operator's own description was "messy", and that is fair: a
credential designed for a program was being typed by people.

## Decision

**Sentinel reads; Sentry manages. The console is protected by a password, not a
shared token.**

Concretely:

- **Sentry's console is the only place device configuration is changed.** The
  UI freeze from ADR-0009 is lifted — there is no longer anywhere else for a
  device feature to go, so freezing this one would freeze the product.
- **Sentinel consumes `GET /api/v1/sdrs` and nothing else.** That endpoint
  already publishes every field Sentinel needs, already filters on the
  per-device `visibility` flag, and is already versioned separately
  (`X-Sentry-Sdr-Api-Version`). It becomes **unauthenticated**, because a
  read-only export of devices an operator has explicitly marked public is the
  one thing here that does not need a credential.
- **`SENTRY_AUTH_TOKEN` is removed entirely.** Its replacement is a console
  password: hashed with argon2id, stored in Sentry's own database, set through
  the UI, and changeable there.
- **The management API is protected by the resulting session**, an
  `HttpOnly; SameSite=Strict` cookie.

## Consequences

**Good.**

- One credential, in one place, that a person can actually use. No pasting a
  64-character hex string once per tab, and changing it is a form rather than a
  shell command and a container recreation.
- **The SSE credential-in-a-URL problem disappears.** `EventSource` cannot set
  headers, so the token had to be accepted via `?access_token=` on
  `GET /api/events` — a credential written into browser history and, without
  the redaction Sentry had to implement, the access log. Cookies are sent
  automatically on same-origin requests, so that whole path is deleted rather
  than mitigated.
- `SameSite=Strict` closes the CSRF exposure a cookie would otherwise introduce.
  This app has no cross-site flow to break, so the strict setting costs nothing.
- Sentinel needs no credential, no configuration, and no coordination when the
  password changes.

**Bad, and accepted.**

- **The published export is now genuinely public.** Anyone who can reach the Pi
  can read the name, host, port, description, notes and antenna of every device
  not marked private. The `visibility` flag stops being "what Sentinel sees" and
  becomes "what anyone sees", which is a heavier meaning than it carried when it
  was written. Operators who used private/public as a tidiness control rather
  than a disclosure control will be surprised.
- **No machine credential remains.** A script or `curl` that manages devices has
  to perform a login and hold a cookie. Nothing in this project does that today,
  but the capability is genuinely gone rather than relocated.
- **One password, one level of access.** Still no user accounts, no read-only
  role, no audit of who changed what. Sharing the password shares everything, as
  sharing the token did. This decision improves the ergonomics of that model, not
  the model.
- **The password crosses a plain-HTTP LAN.** There is no TLS here and this ADR
  does not add any. A human-chosen password is more valuable to an attacker than
  a single-purpose random token, because people reuse passwords — so this is a
  real, if modest, regression in one narrow respect. It is accepted because the
  threat it addresses (someone already on your LAN, sniffing traffic) is a
  different and larger problem than the one this ADR solves.
- ADR-0009's dual-control design is reversed after five days. The cost of that
  is mostly this document.

## Alternatives considered

**Keep the token, persist it in `localStorage`.** One line, and it removes the
per-session pasting entirely — the actual complaint. Rejected because it leaves
the rest: the credential is still a shared secret with no notion of changing it
short of a shell command, and still one that a person has to store and hand
around. It fixes the friction without fixing the shape.

**Password *and* token, side by side** — password for humans, token for machines.
Rejected as two authentication systems to maintain for a machine consumer that,
under this ADR, no longer needs to authenticate at all. Worth revisiting the day
something genuinely needs programmatic write access.

**Keep ADR-0009 and enforce the freeze properly.** Rejected on evidence: it was
not enforced when it was current and unambiguous, by people who had read it. A
rule that requires more discipline than it has historically received is not a
plan.

**User accounts with roles.** Rejected as premature. The need described was one
operator, occasionally sharing access with someone equally trusted. Accounts
earn their keep at "my neighbour can view but not touch", which nobody has asked
for. This ADR does not preclude it.

## Notes

The deploy-time gates from ADR-0007 (`SENTRY_HOTSPOT_CONTROL_ENABLED`) are
unaffected and stay in `.env`. Their value is precisely that they require shell
access to the Pi, which a console password does not confer.

`GET /api/health` remains unauthenticated, as it was under ADR-0009: the Docker
healthcheck must reach it regardless, and it exposes counts rather than
identities.
