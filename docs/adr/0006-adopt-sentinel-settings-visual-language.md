# ADR-0006 — Adopt Sentinel's settings visual language, palette included

- **Status:** Accepted
- **Date:** 2026-08-02
- **Deciders:** project owner
- **Context spec:** [`docs/architecture/sentry-fleet-manager.md`](../architecture/sentry-fleet-manager.md) §9.5
- **Supersedes:** the "sibling, not twin" design direction recorded in §9.5 (no prior ADR — the
  direction lived only in the architecture spec)

## Context

§9.5 chose a **sibling** relationship with Sentinel: inherit the near-black ground and the Barlow
type system so the two apps read as family, but move the accent from Sentinel's lime `#c8ff00` to
signal amber `#ffb020`. The stated reason was operational: an operator will often have both apps
open on one screen describing the same dongles, and "which window am I in?" is a real error when
one of those windows can flash a dongle's EEPROM.

That direction was built and shipped. In use, the judgement changed. Sentinel's **settings
section** — its card grid, square corners, flat fills, uppercase Barlow legends and light canvas —
is the house style the owner wants Sentry to be *in*, not adjacent to. The two tools are one
system, and an operator moving between them should not be crossing a visual boundary at all. The
window-confusion risk was reassessed as smaller than the cost of the two consoles looking like
different products: Sentry's content (a device grid, a USB tree) is nothing like any Sentinel
screen, so the page identifies itself by what is on it.

## Decision

**Adopt Sentinel's settings section wholesale — structure, typography and palette.**

Layout and type, taken from Sentinel's `SettingsPanel.css`:

- Card grid, `repeat(auto-fill, minmax(min(300px,100%), 1fr))`, 16px gutter, 1480px measure.
- Cards: square, flat fill, 22px padding, a label/description block above the control.
- Square corners throughout (`borderRadius.rack: 0`); 4px on status chips and 6px on buttons and
  inset notices are the only exceptions, matching Sentinel.
- The five-step uppercase tracking scale (0.1 / 0.14 / 0.16 / 0.18 / 0.22em), 44px page gutter.

Palette, using Sentinel's own values:

| Role | Value |
|---|---|
| Canvas | `#f6f6f4` |
| Card | `#ffffff` |
| Input / flat-row fill | `#e8eaed` |
| Accent | `#c8ff00`, with `#0a0c10` on it |

**The accent is a fill and never anything else.** Lime is 1.18:1 on white — below the 3:1 floor
for a non-text indicator, let alone the 4.5:1 for text. It appears only as a solid fill behind
near-black text: the primary button, the active toggle, the heading dot, the skip link. This is
how Sentinel's own settings panel uses it. Everywhere the accent is needed *as* a colour — the
`streaming` state label, its card stripe, a success message — the token `signal.ok` (`#4a7200`)
stands in as its text-safe form.

Semantic tones are named for meaning rather than hue (`ok`, `warn`, `danger`, `info`, `muted`,
`faint`), because on this palette the tone that means "lime" is an olive.

## Consequences

**Positive**

- **One product, one surface.** Moving between Sentinel and Sentry no longer crosses a visual
  boundary, which is the outcome the owner wanted.
- **The layout vocabulary is proven.** The card grid, the labelled-input shell and the flat data
  rows are lifted from a shipped, exercised UI rather than invented here.
- **Contrast is better than the source.** See below — several Sentinel values fail AA and were
  corrected rather than copied.
- **The palette is now enforceable.** Because the accent is fill-only, the rule "never
  `text-signal-accent` or `border-signal-accent`" is greppable, and the token names make a misuse
  read as wrong at the call site.

**Negative**

- **The window-confusion risk from §9.5 is now real and accepted.** Two windows on one screen no
  longer differ by accent colour. The mitigation is content and the page title, not chrome. If
  this bites in practice, the cheapest fix is a persistent identifying band in `FleetHeader` — not
  a palette fork, which would put us back here.
- **A light theme is worse in a dark room.** Sentry runs on a Pi that may sit in a rack room or a
  loft. Sentinel's settings panel is a modal an operator visits briefly; Sentry's console is a page
  they may leave open. No dark mode exists today.
- **The "Patch Bay" identity is largely spent.** The jack pair survives; the near-black instrument
  panel, the amber focus ring and the amber connector motifs do not. §9.5 has been rewritten.
- **Sentinel's design is now an upstream dependency in practice.** If its settings section is
  restyled, Sentry drifts. Nothing enforces the link — no shared package, no token export.

**Where the match is deliberately inexact**

Copied literally, Sentinel's type colours fail WCAG 2.2 AA, which Sentry treats as a required bar:

- Secondary text at `rgba(16,19,29,.5)` is 3.49:1 on white; muted group labels at `.35` are ~2.6:1.
  Sentry darkens these to `#66686e` (4.62:1 on the darkest ground it lands on, the input fill).
- Every semantic tone was re-derived to clear 4.5:1 against **all three** grounds, with the
  `#e8eaed` input fill as the binding constraint since field labels and badge text sit on it.
- `signal.faint` (`#8a8d92`) is the one sub-threshold tone: 3.08:1, non-text use only, for idle
  state stripes and glyphs whose label is rendered in `signal.muted` alongside.
- The focus ring is ink `#23262f` (13.96:1), not the accent — a lime ring at 1.18:1 is not a focus
  indicator. Likewise the field's focus underline uses `signal.ok`; Sentinel draws that in raw
  lime, where it is decorative rather than legible.
- The dialog scrim is an ink wash, not a wash of the page ground: near-white over near-white dims
  nothing and the modal stops reading as modal.

**Rejected alternatives**

- **Keep amber as the accent on Sentinel's light palette.** Recommended at the time and rejected
  by the owner. It preserved the window-distinguishing cue and, as a fill behind dark text, amber
  is a slightly stronger surface than lime — but it leaves the two apps visibly different, which
  is the thing being fixed.
- **Structure without palette** (the intermediate state this work passed through). Sentry took
  Sentinel's grid, card anatomy and tracking scale while staying on the near-black ground. It
  looked coherent, but it reads as a dark theme *of* Sentinel rather than the same product — the
  half-measure that prompted this ADR.
- **Port Sentinel's CSS directly.** `SettingsPanel.css` is 1,543 lines of id-scoped selectors
  written against Sentinel's DOM. Sentry is Tailwind-with-components; the values transferred, the
  stylesheet could not.
