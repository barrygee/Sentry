import { classes, el } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { syncChildren } from './childrenSync.js'

/**
 * A short uppercase status label: 9px Barlow 700 at 0.18em, coloured by tone.
 *
 * Unfilled. It was a tinted chip — a 12% wash of its own tone, matching a
 * segmented control's active option — but a fill behind the device state read
 * as a third coloured surface on a card that already carries the state as a
 * glyph. It is now the label alone, as the rest of the card is.
 *
 * `neutral` is white rather than grey: the device state is the only 9px
 * uppercase label on a card that is not a field title, and left muted it read
 * as an oversight beside them rather than as a different kind of thing. The
 * state's own colour is carried by `StatusDot`'s glyph, so nothing is lost.
 *
 * Every tone's text colour is verified >=4.5:1 against Sentry's grounds (see
 * `tailwind.config.ts`), which the fill's removal only improves.
 */
export type StatusBadgeTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info'

export interface StatusBadgeProps {
  tone?: StatusBadgeTone
  children: Child[]
}

const TONE_CLASSES = {
  neutral: 'text-ink-primary',
  // Not the raw accent: lime is 1.18:1 on this light ground and unreadable
  // as text. `ok` is its text-safe form.
  accent: 'text-signal-ok',
  ok: 'text-signal-ok',
  warn: 'text-signal-warn',
  danger: 'text-signal-danger',
  info: 'text-signal-info',
} as const satisfies Record<StatusBadgeTone, string>

const BASE_CLASSES =
  'inline-flex items-center gap-1.5 font-sans text-[10px] font-semibold uppercase tracking-legend'

/** Builds a `StatusBadge`. `update` mutates the same element in place. */
export function statusBadge(props: StatusBadgeProps): Component<StatusBadgeProps> {
  const root = el(
    'span',
    { class: classes(BASE_CLASSES, TONE_CLASSES[props.tone ?? 'neutral']) },
    props.children,
  )

  return {
    element: root,

    update(nextProps): void {
      root.className = classes(BASE_CLASSES, TONE_CLASSES[nextProps.tone ?? 'neutral'])
      syncChildren(root, nextProps.children)
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
