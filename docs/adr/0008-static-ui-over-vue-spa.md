# ADR-0008 — Replace the Vue SPA with a static, framework-free TypeScript UI

- **Status:** Accepted (its accessibility-testing mitigation withdrawn by [ADR-0011](0011-drop-automated-accessibility-testing.md))
- **Date:** 2026-08-04
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-sdr-controller.md`](../architecture/sentry-sdr-controller.md)
- **Supersedes the frontend row of:** §5 technology choices

## Context

Sentry's operator console was a Vue 3 + Vite + Pinia SPA: 50 single-file components, roughly 8,200
lines, with a `node:22-alpine` build stage in the image and a dependency tree of some 240 packages.

Two things changed the calculus.

First, **Sentinel is becoming the primary console.** Its SDR settings section is being extended to
manage Sentry's devices — naming, port assignment, public/private, notes, antenna, tuning — and to
control the hotspot, all over Sentry's HTTP API (ADR-0009). Sentry's own UI stops being the place
the operator normally works and becomes a **local fallback**: the thing you reach for when Sentinel
cannot see the Pi, which is precisely when the WiFi is misconfigured and the network is the problem.

Second, that reframing changes what the UI has to be good at. A fallback console needs to be
**present and dependable**, not feature-rich. It will not grow: everything new lands in Sentinel.
Carrying a framework, a bundler and 240 packages to serve a console that is now frozen at its
current feature set is paying a recurring maintenance and supply-chain cost for capability that is
deliberately not going to be used.

The project owner's requirement was explicit: keep a basic UI in Sentry, keep the layout and styles
exactly as they are, keep the functionality, but a Vue app is not needed.

## Decision

Rebuild the console as **static HTML + browser-native ES modules, written in strict TypeScript, with
Tailwind retained**.

- `tsc` emits ES2022 modules straight to `dist/js`. No bundler. Import specifiers are relative and
  carry a `.js` extension, because tsc does not rewrite them.
- The **Tailwind CLI** compiles one stylesheet from `tailwind.config.ts` — unchanged, including every
  design token and the contrast reasoning behind it. This is what guarantees the visual output is
  identical rather than approximately similar; hand-translating utility classes would have drifted.
- The app shell — header, nav rail, headings, live regions, skip link — is **static markup in
  `index.html`**. It never changes shape, and keeping it as markup means it is in the document
  before a module has parsed.
- Components become factories returning `{ element, update, destroy }` (`core/component.ts`). They
  build their DOM once and **mutate in place**. There is no virtual DOM and no re-render, because
  this console edits device names, ports, notes and antennas inline — replacing a subtree while the
  operator is typing would move focus and drop the caret.
- Pinia stores become `createStore` singletons (`core/observable.ts`): one immutable state object,
  `setState` as the only mutation path, subscriber notification coalesced to a microtask. Not deeply
  reactive by design — a stray in-place edit cannot silently desynchronise the DOM.
- Modal semantics are centralised in `core/focusTrap.ts` and the live regions in
  `core/liveAnnouncer.ts`, so the behaviours a framework used to guarantee have exactly one
  implementation each.

## Consequences

**Good.**

- The image's frontend build stage is `tsc` + Tailwind CLI + a copy. Runtime dependencies: none. The
  final image is unchanged in shape — node was already build-only — but the build is smaller, faster
  and has far less to go wrong in it.
- The dependency tree drops from ~240 packages to 11 dev dependencies.
- Rendering behaviour is now explicit. Where the Vue version relied on reconciliation heuristics to
  preserve focus in inline-edited fields, the port preserves it by construction.

**Bad, and accepted.**

- **`eslint-plugin-vuejs-accessibility` is gone and nothing replaces it.** It caught missing labels,
  unlabelled controls and handlers on static elements *statically*, and it only ever worked on `.vue`
  templates — there is no equivalent rule set for markup built imperatively. This is a real reduction
  in cover on the project's highest-priority non-functional requirement.

  The mitigation proposed here — a mandatory Playwright + axe smoke suite — was **withdrawn by
  [ADR-0011](0011-drop-automated-accessibility-testing.md)** and never built. Every ARIA attribute,
  `role`, `tabindex`, accessible name and focus behaviour was carried over verbatim in the port, and
  nothing enforces that they stay. That is now the standing position rather than a temporary gap.

- More code is written by hand: `keyedList`, `switchChild`, the focus trap, the store. That is
  roughly 400 lines of infrastructure a framework used to supply, and it is ours to maintain.

- The console had **no frontend tests before this change and has none after it**, so the port itself
  was verified by build, typecheck, and manual exercise against `tools/mock_sentry.py` (render, SSE
  live updates, dialog open, focus trap, Escape, focus restoration, zero console errors) rather than
  by a suite. (A frontend test harness and suites arrived later; the axe suite this ADR called for
  did not — see [ADR-0011](0011-drop-automated-accessibility-testing.md).)

## Alternatives considered

**Keep Vue.** Rejected on the reframing above: the cost is recurring, the capability is now unused,
and the console is frozen at parity by design.

**Hand-extract Tailwind to plain CSS and drop Node entirely.** Tempting — it would remove the last
build step and match the project's static-site standards exactly. Rejected because "the layout and
styles should remain as is" was a hard requirement, and hand-translating ~8,000 lines of utility
classes would have drifted from the original in places no one would notice until they looked. The
Tailwind CLI keeps the output provably identical for one small command.

**Server-rendered Jinja2 templates.** Rejected: the console is live — SSE drives continuous device
state changes — so the client needs the rendering logic regardless. Templates would have added a
second rendering path without removing the first.
