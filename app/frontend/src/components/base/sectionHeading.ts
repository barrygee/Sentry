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
 * There is no accent dot. An earlier version prefixed every heading with one,
 * which is what made it meaningless. It now appears only on the two view
 * titles (`index.html`), where it marks the destination the rail switched to —
 * a box heading inside one of those views is not that.
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
  size?: 'default' | 'small'
  children: Child[]
}

const HEADING_TAGS = { 1: 'h1', 2: 'h2', 3: 'h3' } as const

const SIZE_CLASSES = {
  default: 'text-[18px]',
  small: 'text-[13px]',
} as const

/** Builds a `SectionHeading`. `update` syncs the same heading element's children in place. */
export function sectionHeading(props: SectionHeadingProps): Component<SectionHeadingProps> {
  const root = el(
    HEADING_TAGS[props.level ?? 2],
    {
      class: `m-0 font-condensed ${SIZE_CLASSES[props.size ?? 'default']} font-normal uppercase leading-tight tracking-readout text-ink-primary`,
    },
    props.children,
  )

  return {
    element: root,

    update(nextProps): void {
      syncChildren(root, nextProps.children)
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
