import { classes, el } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { chevronIcon } from './chevronIcon.js'
import { syncChildren } from './childrenSync.js'

/**
 * A collapsible section: a summary row with a right-aligned chevron, and a body
 * that the browser shows and hides itself.
 *
 * Extracted from `AbsentDeviceGroup`, which had the only copy of this markup.
 * A second caller (the hotspot's DHCP leases) needed the identical disclosure,
 * and duplicating a `<details>`/`<summary>`/chevron trio is exactly how two
 * accordions drift into looking like two different controls.
 *
 * **Native `<details>`, not a hand-rolled toggle.** The browser owns the
 * open/closed state, which is what keeps keyboard operation, find-in-page
 * expansion and the disclosure role correct for free. The chevron is mirrored
 * off the element's own `toggle` event rather than driven by a prop, so it can
 * never disagree with what is actually showing.
 *
 * The chevron is Sentinel's: it points right when closed and rotates down when
 * open (`rotate(-90deg)` → `rotate(0deg)`), pinned to the right edge with
 * `ml-auto` so the label stays left-aligned however long it is.
 */
export interface DisclosureSectionProps {
  /** The summary row's label. */
  label: Child[]
  /** The body revealed when open. */
  children: Child[]
  /**
   * Wrap the label in a heading of this level.
   *
   * Omit for a bare group label (`AbsentDeviceGroup`'s case — it labels a
   * grouping, not a section of the document). Supply it when the disclosure
   * genuinely heads a section, so collapsing it does not punch a hole in the
   * page outline a screen-reader user navigates by. `<summary>`'s content
   * model permits heading content, so this stays valid HTML.
   */
  headingLevel?: 2 | 3
  /**
   * `group` — a muted 10px grouping label, de-emphasised against the content.
   * `section` — the 11px field-label vocabulary shared with `BaseField`, so a
   * section inside a settings box reads as a peer of the fields around it
   * rather than as a differently-sized heading.
   */
  tone?: 'group' | 'section'
  /** Open on first render. Read once — the browser owns the state after that. */
  defaultOpen?: boolean
}

const TONE_CLASSES = {
  group: 'text-[10px] tracking-control text-signal-muted',
  section: 'text-[11px] tracking-label text-ink-primary',
} as const

// `justify-between` is what actually pins the chevron right, and it has to be:
// `ChevronIcon`'s root is a `display: contents` wrapper, so it generates no box
// of its own and an `ml-auto` on it is silently a no-op — the SVG inside is the
// real flex item here. The inherited `absentDeviceGroup` code set that margin
// and never got the alignment it was asking for.
const SUMMARY_CLASSES =
  'flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-2 rounded-rack py-3 font-sans font-semibold uppercase transition-colors hover:text-ink-primary [&::-webkit-details-marker]:hidden'

const HEADING_TAGS = { 2: 'h2', 3: 'h3' } as const

/** Builds a `DisclosureSection`. `update` replaces the label and body in place. */
export function disclosureSection(
  props: DisclosureSectionProps,
): Component<DisclosureSectionProps> {
  const chevron = chevronIcon({ open: props.defaultOpen ?? false })

  // The label lives in its own element either way, so `update` can swap its
  // children without disturbing the chevron beside it.
  const labelHost =
    props.headingLevel === undefined
      ? el('span', {}, props.label)
      : // Tailwind's preflight already resets a heading's size and weight to
        // `inherit`, so the summary's own type treatment carries through and
        // the heading contributes semantics only.
        el(HEADING_TAGS[props.headingLevel], { class: 'm-0' }, props.label)

  const summary = el(
    'summary',
    { class: classes(SUMMARY_CLASSES, TONE_CLASSES[props.tone ?? 'group']) },
    [labelHost, chevron.element],
  )

  const body = el('div', { class: 'flex flex-col gap-4 pb-card' }, props.children)

  const details = el(
    'details',
    {
      class: 'group rounded-rack',
      attrs: props.defaultOpen ? { open: true } : {},
      on: {
        toggle: (event) => {
          chevron.update({ open: (event.target as HTMLDetailsElement).open })
        },
      },
    },
    [summary, body],
  )

  return {
    element: details,

    update(nextProps): void {
      // `syncChildren`, never `replaceChildren`: the body holds live controls,
      // and detaching them on every update blurs whatever currently has focus.
      syncChildren(labelHost, nextProps.label)
      syncChildren(body, nextProps.children)
    },

    destroy(): void {
      chevron.destroy()
    },
  }
}
