import { classes, el } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { svgEl } from './svg.js'

/**
 * Sentinel's disclosure chevron (`ChevronIcon` / `.bfp-item-chevron`), drawn
 * at the same 10px box with the same 1.3 round-capped stroke so a Sentry
 * accordion and a Sentinel side-panel accordion carry the identical mark.
 *
 * Points right when closed and down when open — Sentinel's own `rotate(-90deg)`
 * → `rotate(0deg)` transition, not a swapped glyph, so the arrow turns rather
 * than blinking from one character to another.
 *
 * Inherits `currentColor`, which is what lets the summary that hosts it drive
 * the colour: dim by default, brightening with the label on hover and while
 * open, exactly as Sentinel's does.
 */
export interface ChevronIconProps {
  open?: boolean
  strokeWidth?: number
}

/** Builds a `ChevronIcon`. `update` mutates the same SVG in place. */
export function chevronIcon(props: ChevronIconProps): Component<ChevronIconProps> {
  const path = svgEl('path', {
    attrs: {
      d: 'M2 3.5L5 6.5L8 3.5',
      stroke: 'currentColor',
      'stroke-width': props.strokeWidth ?? 1.3,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    },
  })

  const svg = svgEl(
    'svg',
    {
      attrs: {
        width: 10,
        height: 10,
        viewBox: '0 0 10 10',
        fill: 'none',
        'aria-hidden': 'true',
      },
      class: classes(
        'block shrink-0 transition-transform duration-200 ease-out motion-reduce:transition-none',
        (props.open ?? false) ? 'rotate-0' : '-rotate-90',
      ),
    },
    [path],
  )

  // `Component.element` must be an `HTMLElement` (the contract every caller
  // relies on), but `svg` is an `SVGSVGElement` — a different interface with
  // no HTML-only members. A `display: contents` wrapper contributes no box of
  // its own, so the SVG still lays out, sizes and rotates exactly as if it
  // were the root, while satisfying the type every other component depends on.
  const root = el('span', { class: 'contents' }, [svg])

  return {
    element: root,

    update(nextProps): void {
      svg.setAttribute(
        'class',
        classes(
          'block shrink-0 transition-transform duration-200 ease-out motion-reduce:transition-none',
          (nextProps.open ?? false) ? 'rotate-0' : '-rotate-90',
        ),
      )
      path.setAttribute('stroke-width', String(nextProps.strokeWidth ?? 1.3))
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
