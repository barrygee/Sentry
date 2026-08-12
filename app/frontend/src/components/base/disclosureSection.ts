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
  /** The summary row's label. Ignored when `summaryContent` is given. */
  label: Child[]
  /**
   * Full custom content for the summary row, replacing `label`.
   *
   * For a summary that is more than a caption — the SDR card puts its whole
   * identity-and-toggles header here. The chevron is still appended after it.
   *
   * **Interactive controls in here need their clicks stopped**, or activating
   * one also toggles the disclosure: a click inside a `<summary>` reaches the
   * summary and triggers its default. `stopPropagation` on the control's own
   * wrapper is enough.
   */
  summaryContent?: Child[]
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
   * `panel` — `SectionHeading`'s `item` size, for a whole settings box whose
   * own title becomes the disclosure. Kept identical to that component's
   * classes so a collapsible box and a fixed one are indistinguishable when
   * open.
   */
  tone?: 'group' | 'section' | 'panel'
  /** Open on first render, when nothing has been remembered. Read once. */
  defaultOpen?: boolean
  /**
   * Remember this disclosure's open state under this key, across reloads.
   *
   * Stored per key in `localStorage`, written on every toggle and read once at
   * construction — where a remembered value wins over `defaultOpen`. Boxes
   * start closed, so without this an operator would re-open the same two every
   * visit; with it, the page comes back the way they left it.
   *
   * Keys must be stable and unique. A device card keys on its `device_id`, so
   * a collapsed card stays collapsed across a replug.
   */
  persistKey?: string
  /**
   * `id` for the heading element, so a surrounding `aria-labelledby` can point
   * at it. Only meaningful alongside `headingLevel`.
   */
  headingId?: string
  /** Extra classes for the body wrapper, for panels whose content wants its own gap. */
  bodyClass?: string
  /**
   * `true` when this disclosure is a box's own title, so the box's `p-card`
   * already supplies the surrounding space and the summary must add none.
   */
  isBoxTitle?: boolean
  /**
   * An element inside `summaryContent` to mount the chevron into, instead of
   * appending it to the summary.
   *
   * Lets a caller put the chevron on a specific line of a multi-line summary —
   * the device card aligns it with its status badge, so the two read as one
   * row rather than the chevron occupying a line of its own.
   */
  chevronSlot?: HTMLElement
}

const TONE_CLASSES = {
  group: 'text-[10px] tracking-control text-signal-muted',
  section: 'text-[11px] tracking-label text-ink-primary',
  panel: 'text-[12px] tracking-[0.1em] text-ink-primary',
} as const

// `justify-between` is what actually pins the chevron right, and it has to be:
// `ChevronIcon`'s root is a `display: contents` wrapper, so it generates no box
// of its own and an `ml-auto` on it is silently a no-op — the SVG inside is the
// real flex item here. The inherited `absentDeviceGroup` code set that margin
// and never got the alignment it was asking for.
// Everything both layouts share. The inline variant adds its own row
// alignment; the `chevronAbove` one stacks instead.
const SUMMARY_CLASSES_BASE =
  'flex cursor-pointer list-none rounded-rack font-sans font-semibold uppercase transition-colors hover:text-ink-primary [&::-webkit-details-marker]:hidden'

const SUMMARY_CLASSES = classes(SUMMARY_CLASSES_BASE, 'items-center justify-between gap-2')

// A standalone disclosure carries its own comfortable target. One that *is* a
// box's title sits inside the box's `p-card`, and adding to that padded the top
// of every box more than its bottom — 42px against 30px. Dropped to the 24px
// WCAG 2.2 AA minimum target size (2.5.8) with no padding of its own, so the
// box's own padding is the only thing setting the gap.
const SUMMARY_SPACING = {
  standalone: 'min-h-[44px] py-3',
  boxTitle: 'min-h-[24px] py-0',
} as const

const HEADING_TAGS = { 2: 'h2', 3: 'h3' } as const

const STORAGE_PREFIX = 'sentry.disclosure.'

/**
 * Read a remembered open state, or `null` when nothing is stored.
 *
 * Every access is guarded: `localStorage` throws on access in a page with
 * cookies blocked, and a disclosure that cannot remember its state must still
 * open and close.
 */
function readRemembered(persistKey: string | undefined): boolean | null {
  if (persistKey === undefined) return null
  try {
    const stored = window.localStorage.getItem(STORAGE_PREFIX + persistKey)
    return stored === null ? null : stored === 'open'
  } catch {
    return null
  }
}

function remember(persistKey: string | undefined, open: boolean): void {
  if (persistKey === undefined) return
  try {
    window.localStorage.setItem(STORAGE_PREFIX + persistKey, open ? 'open' : 'closed')
  } catch {
    // Storage unavailable or full. The disclosure still works; it just forgets.
  }
}

/** Builds a `DisclosureSection`. `update` replaces the label and body in place. */
export function disclosureSection(
  props: DisclosureSectionProps,
): Component<DisclosureSectionProps> {
  // A remembered state wins over the default: the default is only what to do
  // the first time, before the operator has expressed a preference.
  const startsOpen = readRemembered(props.persistKey) ?? props.defaultOpen ?? false

  const chevron = chevronIcon({ open: startsOpen })

  // The label lives in its own element either way, so `update` can swap its
  // children without disturbing the chevron beside it.
  const labelHost = props.summaryContent
    ? el('div', { class: 'contents' }, props.summaryContent)
    : props.headingLevel === undefined
      ? el('span', {}, props.label)
      : // Tailwind's preflight already resets a heading's size and weight to
        // `inherit`, so the summary's own type treatment carries through and
        // the heading contributes semantics only.
        el(
          HEADING_TAGS[props.headingLevel],
          { class: 'm-0', ...(props.headingId ? { attrs: { id: props.headingId } } : {}) },
          props.label,
        )

  if (props.chevronSlot) {
    props.chevronSlot.appendChild(chevron.element)
  }

  const summary = el(
    'summary',
    {
      class: classes(
        props.chevronSlot ? SUMMARY_CLASSES_BASE + ' flex-col items-stretch' : SUMMARY_CLASSES,
        SUMMARY_SPACING[props.isBoxTitle ? 'boxTitle' : 'standalone'],
        TONE_CLASSES[props.tone ?? 'group'],
      ),
    },
    props.chevronSlot ? [labelHost] : [labelHost, chevron.element],
  )

  const body = el(
    'div',
    { class: props.bodyClass ?? 'flex flex-col gap-4 pb-card' },
    props.children,
  )

  const details = el(
    'details',
    {
      class: 'group rounded-rack',
      attrs: startsOpen ? { open: true } : {},
      on: {
        toggle: (event) => {
          const open = (event.target as HTMLDetailsElement).open
          chevron.update({ open })
          remember(props.persistKey, open)
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
      syncChildren(labelHost, nextProps.summaryContent ?? nextProps.label)
      syncChildren(body, nextProps.children)
    },

    destroy(): void {
      chevron.destroy()
    },
  }
}
