import { el } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { syncChildren } from './childrenSync.js'

/**
 * The device stack: one centred column, cards laid out vertically.
 *
 * This replaced an auto-filling card grid that placed cards side by side at
 * wider viewports. A set of SDRs is a handful of dongles, and reading them as a
 * single ordered list beats packing them into columns. The centred 860px
 * measure they sit in belongs to the page wrapper, shared with the notices and
 * banners above them.
 *
 * Renders a `<div>` by default. Pass `as="ul"` when the cards are a genuine
 * list of like things, in which case the caller wraps each in an `<li>`.
 * `as` is read once at construction — like every other structural tag choice
 * in this port, a stack's host element does not change after mount.
 */
export interface PanelStackProps {
  as?: 'div' | 'ul'
  children: Child[]
}

/** Builds a `PanelStack`. `update` syncs the same list container's children in place, preserving whatever inside a card (a device name mid-rename) currently holds focus. */
export function panelStack(props: PanelStackProps): Component<PanelStackProps> {
  const root = el(
    props.as ?? 'div',
    { class: 'm-0 flex list-none flex-col gap-4 p-0' },
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
