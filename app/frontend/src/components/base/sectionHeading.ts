import { el } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { syncChildren } from './childrenSync.js'

/**
 * A dialog or section title, in Sentinel's condensed-title style — the same
 * treatment it gives a station name (`Barlow Condensed`, uppercase, lightly
 * tracked) rather than the 9px legends it uses for section labels, which are
 * far too small to head a modal.
 *
 * `level` picks the heading element so the page keeps a correct outline
 * without the caller restating the visual treatment. Read once at
 * construction — a heading's level does not change after mount.
 *
 * The accent dot is opt-in, via `accentDot`. An earlier version put one on
 * every heading, which is what made it meaningless; Sentinel spends it on
 * section headings only, and reserving it for those is what keeps it a marker
 * for "this is a section" rather than decoration.
 */
export interface SectionHeadingProps {
  /** Heading level, 1-3. Defaults to `2`. */
  level?: 1 | 2 | 3
  /**
   * Visual size, independent of `level`.
   *
   * Kept separate on purpose: a subsection inside a panel needs a smaller
   * heading than the panel's own, but it still has to be an `h3` for the page
   * outline to make sense to a screen reader. Tying size to level would force a
   * choice between correct semantics and correct typography.
   *
   * Set at construction, like `level` — headings do not resize after mount.
   */
  size?: 'default' | 'small' | 'section'
  /**
   * Prefix a small accent dot, as Sentinel's section headings do.
   *
   * Decorative, so it is `aria-hidden` — a screen reader announcing "bullet"
   * before every section title would be noise, and the heading level already
   * conveys the structure the dot is drawing.
   */
  accentDot?: boolean
  children: Child[]
}

const HEADING_TAGS = { 1: 'h1', 2: 'h2', 3: 'h3' } as const

const SIZE_CLASSES = {
  default: 'text-[18px] font-normal tracking-readout',
  small: 'text-[13px] font-normal tracking-readout',
  // Sentinel's `#settings-section-heading`, field for field: 21px, 600,
  // 0.16em tracking.
  section: 'text-[21px] font-semibold tracking-[0.16em]',
} as const

/** The heading's children, preceded by the accent dot when one was asked for. */
function childrenWithDot(props: SectionHeadingProps): Child[] {
  if (!(props.accentDot ?? false)) {
    return props.children
  }
  return [
    el('span', {
      attrs: { 'aria-hidden': 'true' },
      class: 'h-1.5 w-1.5 shrink-0 rounded-full bg-signal-accent',
    }),
    ...props.children,
  ]
}

/** Builds a `SectionHeading`. `update` syncs the same heading element's children in place. */
export function sectionHeading(props: SectionHeadingProps): Component<SectionHeadingProps> {
  const root = el(
    HEADING_TAGS[props.level ?? 2],
    {
      class: `m-0 flex items-center gap-3 font-condensed ${SIZE_CLASSES[props.size ?? 'default']} uppercase leading-tight text-ink-primary`,
    },
    childrenWithDot(props),
  )

  return {
    element: root,

    update(nextProps): void {
      // Rebuilt through the same helper, or an update would drop the dot the
      // first render added.
      syncChildren(root, childrenWithDot(nextProps))
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
