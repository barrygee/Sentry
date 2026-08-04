import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'

/**
 * The rack-blank-plate empty state (architecture §9.5): terse, no
 * illustration, no marketing tone.
 *
 * Sentinel's `.settings-empty` is bare text on the canvas with no container
 * at all. Sentry keeps a dashed panel around it, because unlike a settings
 * section that is simply empty, "no devices detected" is a state an operator
 * needs to see occupying the slot where hardware would be.
 */
export interface EmptyStateProps {
  title: string
  detail?: string | null
}

/** Builds an `EmptyState`. `update` mutates the same title/detail text in place. */
export function emptyState(props: EmptyStateProps): Component<EmptyStateProps> {
  const titleParagraph = el(
    'p',
    { class: 'font-sans text-[11px] font-semibold uppercase tracking-control text-signal-muted' },
    [props.title],
  )
  const detailParagraph = el(
    'p',
    { class: 'max-w-prose text-[12.5px] leading-[1.55] text-signal-muted' },
    [],
  )

  const root = el(
    'div',
    {
      class:
        'flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-rack bg-ground-panel px-6 py-10 text-center',
    },
    [titleParagraph, detailParagraph],
  )

  function applyDetail(detail: string | null | undefined): void {
    setVisible(detailParagraph, Boolean(detail))
    setText(detailParagraph, detail ?? '')
  }

  applyDetail(props.detail)

  return {
    element: root,

    update(nextProps): void {
      setText(titleParagraph, nextProps.title)
      applyDetail(nextProps.detail)
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
