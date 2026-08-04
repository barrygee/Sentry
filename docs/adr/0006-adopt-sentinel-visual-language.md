# ADR-0006 — Adopt Sentinel's visual language, palette included

- **Status:** Accepted
- **Date:** 2026-08-02
- **Deciders:** project owner
- **Context spec:** [`docs/architecture/sentry-sdr-controller.md`](../architecture/sentry-sdr-controller.md) §9.5
- **Supersedes:** the "sibling, not twin" design direction recorded in §9.5 (no prior ADR — the
  direction lived only in the architecture spec)

## Context

§9.5 chose a **sibling** relationship with Sentinel: inherit the near-black ground and the Barlow
type system so the two apps read as family, but move the accent from Sentinel's lime `#c8ff00` to
signal amber `#ffb020`. The stated reason was operational: an operator will often have both apps
open on one screen describing the same dongles, and "which window am I in?" is a real error when
one of those windows can flash a dongle's EEPROM.

That direction was built and shipped. In use, the judgement changed. The two tools are one system,
and an operator moving between them should not be crossing a visual boundary at all. The
window-confusion risk was reassessed as smaller than the cost of the two consoles looking like
different products: Sentry's content (a device grid, a USB tree) is nothing like any Sentinel
screen, so the page identifies itself by what is on it.

Two things then had to be pinned down, because "match Sentinel" is ambiguous — Sentinel contains
two distinct looks:

1. Its **dark application chrome** (`assets/template.css` `:root`, the SDR panel): black ground,
   lime accent, Barlow legends. This is Sentinel as an operator sees it almost all the time.
2. Its **settings panel** (`SettingsPanel.css`), a deliberately *light* surface scoped inside that
   dark app — a modal an operator visits briefly.

## Decision

**Match Sentinel's dark application chrome, using its own token values.**

| Sentinel | Value | Sentry token |
|---|---|---|
| `--color-bg` | `#000000` | `ground.page` |
| SDR panel surface | `rgba(10,13,20,.92)` | `ground.panel` |
| `--color-button-bg` | `#26292e` | `ground.raised` |
| `--color-border` | `rgba(255,255,255,.08)` | `ground.hairline` |
| `--color-text` | `rgba(255,255,255,.9)` | `ink.primary` |
| `--color-accent` | `#c8ff00` | `signal.accent` |

**Typography is Barlow throughout**, matching Sentinel: legends are Barlow 400 uppercase on a wide
tracking scale (Sentinel's `.sdr-field-label` is 9px/400/0.18em), and numerics are Barlow with
`tabular-nums`. Barlow Condensed is reserved for large readouts, as Sentinel does.

**Layout keeps the settings panel's structure** — the card grid, 22px card padding, 44px gutter,
1480px measure and square corners — because Sentry's content is a grid of records and Sentinel's
dark chrome has no equivalent to copy. Structure from the settings panel; surface and type from
the dark app.

**On this palette the accent is text again.** Lime is 17.76:1 on black, and Sentinel uses it that
way — its active segmented option is lime *text* on a `rgba(200,255,0,.12)` fill. `signal.ok` and
`signal.accent` are therefore the same value, since a healthy Sentry chain and Sentinel's live
indicator are deliberately the same colour.

## Consequences

**Positive**

- **One product, one surface.** Moving between Sentinel and Sentry no longer crosses a visual
  boundary, which is the outcome the owner wanted.
- **Dark suits the deployment.** Sentry runs on a Pi that may sit in a rack room or a loft, and its
  console is a page an operator leaves open — unlike Sentinel's settings modal.
- **Dropping the monospace fixed a real defect, not just a mismatch.** Sentry's `font-mono` named
  JetBrains Mono, which ships in neither project, so every port, frequency and serial silently
  rendered in the system face (Menlo on macOS, something else elsewhere). Barlow with
  `tabular-nums` is both correct and consistent with Sentinel.
- **Contrast is better than the source.** See below — several Sentinel values fail AA and were
  corrected rather than copied.

**Negative**

- **The window-confusion risk from §9.5 is now real and accepted.** Two windows on one screen no
  longer differ by accent colour. The mitigation is content and the page title, not chrome. If this
  bites in practice, the cheapest fix is a persistent identifying band in `SdrsHeader` — not a
  palette fork, which would put us back here.
- **The "Patch Bay" identity is largely spent.** The jack pair and the state stripe survive; the
  amber accent, the amber focus ring and the amber connector motifs do not. §9.5 has been
  rewritten.
- **Sentinel's design is now an upstream dependency in practice.** If its chrome is restyled, Sentry
  drifts. Nothing enforces the link — no shared package, no token export, and the values here are
  transcribed by hand rather than imported.
- **Sentry now spans two of Sentinel's looks** — dark chrome plus settings-panel structure. That is
  a defensible split (surface vs layout), but it is a judgement, and a future reader may reasonably
  ask why the card grid came from the light panel.

**Where the match is deliberately inexact**

Copied literally, some Sentinel values fail WCAG 2.2 AA, which Sentry treats as a required bar:

- Sentinel's `.sdr-field-label` is `rgba(255,255,255,.25)` — 2.25:1 on the control fill. Its own CSS
  acknowledges the class of problem elsewhere ("rgba(…, 0.18) only managed ~1.68:1"). Sentry's muted
  tone is `#9a9ea3` (5.42:1 on that fill) instead.
- Every semantic tone was verified against all three surfaces, with `ground.raised` (`#26292e`)
  binding as the lightest. `signal.danger` keeps Sentinel's `#ff5050` only because it clears 4.5:1
  there (4.53:1) — it had no margin to spare.
- `signal.faint` (`#797e84`) is non-text: it clears 3:1 on every surface for idle-state stripes and
  glyphs, whose labels render in `signal.muted` alongside.
- Neither project ships `BarlowCondensed-300`, so Sentinel's `font-weight: 300` on its large
  readouts is synthesised by the browser. Sentry asks for 400 rather than chase a weight that does
  not exist.

**Rejected alternatives**

- **Keep amber as the accent.** The §9.5 position, and the one that preserved the
  window-distinguishing cue. Rejected by the owner in favour of a full match.
- **Match the light settings panel** — the state this work passed through before landing here.
  Built and reviewed, then rejected: it is Sentinel's *exception*, not its identity. A light page is
  wrong for a console left open in a dark room, and it forced the accent to be fill-only, since lime
  is 1.18:1 on white. That single constraint rippled into a second "text-safe lime" token, an ink
  focus ring and a substituted field underline — none of which this decision needs.
- **Structure without palette.** Sentry took Sentinel's grid and tracking scale while staying on its
  own near-black "Patch Bay" ground. Coherent, but it read as a dark theme *of* Sentinel rather than
  the same product.
- **Port Sentinel's CSS directly.** `SettingsPanel.css` alone is 1,543 lines of id-scoped selectors
  written against Sentinel's DOM. Sentry is Tailwind-with-components; the values transferred, the
  stylesheets could not.
