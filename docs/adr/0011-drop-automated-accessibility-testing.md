# ADR-0011 — Drop automated accessibility testing as a requirement

- **Status:** Accepted
- **Date:** 2026-08-09
- **Deciders:** project owner
- **Amends:** [ADR-0008](0008-static-ui-over-vue-spa.md) (which made the axe suite mandatory)

## Context

ADR-0008 retired the Vue SPA and, with it, `eslint-plugin-vuejs-accessibility` —
which caught missing labels, unlabelled controls and handlers on static elements
*statically*, and only ever worked on `.vue` templates. That ADR recorded the
loss honestly and committed to a replacement:

> The mitigation is runtime, not static: a **Playwright + axe smoke suite is now
> mandatory**, not optional. […] Adding the axe smoke suite is the first thing
> that should follow this ADR.

It was not the first thing that followed, and after several sessions of work it
had been deferred repeatedly in favour of things with a clearer payoff — a
crash-loop outage, an authentication rewrite, CI. A component-level `jest-axe`
pass exists on one component; the assembled-page suite does not.

The project owner has decided it is not going to be built.

## Decision

**Automated accessibility testing is not a requirement of this project.**

- The Playwright + axe smoke suite ADR-0008 made mandatory is **withdrawn**. It
  is not owed, not outstanding, and not a gap anyone should feel obliged to
  close.
- New components do not need an accessibility test.
- The existing `jest-axe` assertion in `tests/components/noticeList.test.ts`
  stays, because it passes and costs nothing. It is an example, not a precedent
  — nothing has to match it.

This changes what is *tested*, not what is *built*. Semantic HTML, accessible
names, keyboard operability and focus management remain how this UI is written;
they are simply no longer verified by a suite.

## Consequences

**Good.**

- The backlog stops carrying an item that was never going to be actioned. A
  requirement that is permanently deferred is worse than no requirement: it
  makes every other outstanding item look equally optional.
- ADR-0008 stops promising something untrue. Its consequences section is
  otherwise unusually honest, and one stale commitment undermines the rest.

**Bad, and accepted.**

- **Nothing enforces accessibility now, statically or at runtime.** The static
  check was lost with Vue; the runtime replacement is withdrawn here. The ARIA
  attributes, roles, `tabindex` values and accessible names carried over verbatim
  in the ADR-0008 port are held in place by review and by nothing else. They will
  drift, and the drift will not be noticed by tooling.
- The most likely losses are the ones the retired lint rule caught cheaply: a
  new control without an accessible name, a handler on a non-interactive element,
  a form field without a label. Each is invisible to sighted mouse use and
  obvious to a screen reader.
- This is a reduction in cover on what the project's own standards called its
  highest-priority non-functional requirement. Recording that plainly is the
  point of this ADR; it is not an argument against the decision, which is the
  owner's to make.

## Alternatives considered

**Keep it as a "should", not a "must".** Rejected as the status quo under another
name: it was already effectively optional, and the ambiguity is what let it sit
unactioned while still appearing in every status summary as outstanding work.

**Keep component-level axe only, drop Playwright.** Rejected as half a rule.
`jest-axe` on a component catches contrast and attribute errors in isolation but
not the assembled-page problems — focus order across a view swap, a heading
hierarchy that only exists once sections are combined — which are the ones worth
a suite. Requiring the cheap half would imply the expensive half was coming.
