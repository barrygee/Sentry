import { classes, el, setAttribute } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { syncChildren } from './childrenSync.js'

/**
 * The inset, tinted callout used for every warning, error and inline
 * explanation: a light wash of its tone carrying matching text, with no border.
 *
 * Its text is the same 12.5px/400/1.55 step the device cards use for their
 * values (Sentinel's `.settings-item-desc`), so an alert reads at the scale of
 * the content around it. It was set a weight heavier, which made alert copy
 * look larger than the card text beside it even though the two matched in size.
 *
 * Each tone is a SOLID fill, not a tint of itself. A wash is a pale ghost of a
 * colour however it is tuned — and these are the loudest things on the page, so
 * they should be the colour rather than a hint of it.
 *
 * The dark tones carry white text, which clears 4.5:1 on each of them (danger
 * 5.49, info 6.16, ok 6.52). `warn` is the exception: it is a bright yellow, so
 * it takes the same near-black `ink.on-accent` that the lime accent does, at
 * 14.6:1 — white on that fill would be 1.4:1. A tone's text colour therefore
 * travels with the tone here rather than being assumed by callers.
 *
 * `neutral` stays a light fill: it carries "this is just so you know", not an
 * alarm, and a solid grey slab would shout as loudly as an error.
 *
 * The caller supplies `role` explicitly rather than this component inferring
 * it from `tone` — whether a message should interrupt a screen-reader user
 * depends on when it appears, not on what colour it is. A banner already on
 * the page at load wants `status` (or nothing at all); one that appears in
 * response to an action wants `alert`.
 */
export type NoticeTone = 'danger' | 'warn' | 'info' | 'ok' | 'neutral'

export interface NoticeBoxProps {
  tone?: NoticeTone
  /** ARIA live semantics. Omit entirely for a notice that is not an announcement. */
  role?: 'status' | 'alert' | null
  /**
   * Extra classes, folded into the rebuilt `className` on every update.
   *
   * A prop rather than something a caller adds to `element.classList`, because
   * `update` reassigns `className` wholesale — anything set from outside would
   * survive until the first state change and then silently vanish.
   *
   * For the rare notice that is a panel rather than a line: the hotspot setup
   * card carries several paragraphs, a code block and a button, and the default
   * `px-4 py-3` that suits a one-line alert leaves that content on the edges.
   */
  extraClasses?: string
  children: Child[]
}

const TONE_CLASSES = {
  danger: 'bg-signal-danger text-white',
  warn: 'bg-signal-warn-fill text-ink-on-accent',
  info: 'bg-signal-info text-white',
  ok: 'bg-signal-ok text-white',
  neutral: 'bg-ground-raised text-signal-muted',
} as const satisfies Record<NoticeTone, string>

const BASE_CLASSES =
  'flex flex-col gap-2 rounded-rack px-4 py-3 text-[12.5px] font-normal leading-[1.55]'

/** Builds a `NoticeBox`. `update` mutates the same container in place. */
export function noticeBox(props: NoticeBoxProps): Component<NoticeBoxProps> {
  const root = el(
    'div',
    {
      attrs: { role: props.role ?? undefined },
      class: classes(BASE_CLASSES, TONE_CLASSES[props.tone ?? 'info'], props.extraClasses),
    },
    props.children,
  )

  return {
    element: root,

    update(nextProps): void {
      setAttribute(root, 'role', nextProps.role ?? null)
      root.className = classes(
        BASE_CLASSES,
        TONE_CLASSES[nextProps.tone ?? 'info'],
        nextProps.extraClasses,
      )
      syncChildren(root, nextProps.children)
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
