import { classes, el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { liveAnnouncer } from '../../core/liveAnnouncer.js'
import { svgEl } from './svg.js'

/**
 * An icon-only action that arms before it fires: a ✕ that, once clicked, is
 * replaced by a ✓ to commit and a ✕ to cancel.
 *
 * This is Sentinel's row-action pattern (`SdrFrequencyManagerTab`'s
 * `.sdr-freq-row-del` family), down to the glyphs, sizes and tones — a bare ✕
 * at 35% white, the confirm tick in accent lime, the cancel ✕ reddening on
 * hover.
 *
 * Focus is moved explicitly at every step, which is the whole reason this is a
 * component rather than a pair of buttons at each call site: each transition
 * *destroys the button the user just activated* (✕ → ✓/✕ → gone), and without
 * intervention focus falls to `<body>`, silently dumping a keyboard user out of
 * the list they were working through. Arming focuses the ✓; cancelling returns
 * focus to the ✕ it came from. This port keeps all three buttons mounted at
 * once and toggles their visibility instead of destroying/recreating them —
 * the same end result, but it means the buttons already exist to receive
 * focus synchronously rather than needing to wait a tick for Vue's DOM patch.
 *
 * Each transition is also announced, since a sighted user sees the glyphs swap
 * but a screen-reader user would otherwise get no signal that a confirmation is
 * now pending.
 */
export interface ConfirmIconActionProps {
  /** Accessible name for the idle ✕, e.g. "Dismiss notice: disk full". */
  accessibleName: string
  /** Accessible name for the ✓ that commits. */
  confirmAccessibleName: string
  /** Accessible name for the ✕ that cancels. */
  cancelAccessibleName: string
  /** Spoken when the action arms, e.g. "Confirm dismissing this notice, or cancel". */
  armedAnnouncement: string
  /** Spoken when the action is cancelled. */
  cancelledAnnouncement: string
  onConfirm: () => void
}

const ACTION_CLASSES =
  'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-rack bg-transparent leading-none transition-colors'

/** Builds a `ConfirmIconAction`. `update` mutates the same three buttons in place; arm/cancel state lives inside the component. */
export function confirmIconAction(
  props: ConfirmIconActionProps,
): Component<ConfirmIconActionProps> {
  let currentProps = props
  let isArmed = false

  const armButton = el(
    'button',
    {
      attrs: { type: 'button', 'aria-label': props.accessibleName },
      class: classes(ACTION_CLASSES, 'text-current opacity-60 hover:opacity-100'),
      on: { click: () => arm() },
    },
    [
      svgEl(
        'svg',
        {
          attrs: {
            width: 12,
            height: 12,
            viewBox: '0 0 14 14',
            fill: 'none',
            stroke: 'currentColor',
            'stroke-width': 1.6,
            'stroke-linecap': 'round',
            'aria-hidden': 'true',
          },
        },
        [svgEl('path', { attrs: { d: 'M3.5 3.5l7 7M10.5 3.5l-7 7' } })],
      ),
    ],
  )

  const confirmButton = el(
    'button',
    {
      attrs: { type: 'button', 'aria-label': props.confirmAccessibleName },
      class: classes(ACTION_CLASSES, 'text-current opacity-90 hover:opacity-100'),
      on: { click: () => confirm() },
    },
    [
      svgEl(
        'svg',
        {
          attrs: {
            width: 13,
            height: 13,
            viewBox: '0 0 14 14',
            fill: 'none',
            stroke: 'currentColor',
            'stroke-width': 1.6,
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
            'aria-hidden': 'true',
          },
        },
        [svgEl('path', { attrs: { d: 'M2.5 7.5l3 3 6-7' } })],
      ),
    ],
  )

  const cancelButton = el(
    'button',
    {
      attrs: { type: 'button', 'aria-label': props.cancelAccessibleName },
      class: classes(ACTION_CLASSES, 'text-current opacity-60 hover:opacity-100'),
      on: { click: () => cancel() },
    },
    [
      svgEl(
        'svg',
        {
          attrs: {
            width: 12,
            height: 12,
            viewBox: '0 0 14 14',
            fill: 'none',
            stroke: 'currentColor',
            'stroke-width': 1.6,
            'stroke-linecap': 'round',
            'aria-hidden': 'true',
          },
        },
        [svgEl('path', { attrs: { d: 'M3.5 3.5l7 7M10.5 3.5l-7 7' } })],
      ),
    ],
  )

  function applyArmedState(): void {
    setVisible(armButton, !isArmed)
    setVisible(confirmButton, isArmed)
    setVisible(cancelButton, isArmed)
  }

  function arm(): void {
    isArmed = true
    applyArmedState()
    liveAnnouncer().announcePolite(currentProps.armedAnnouncement)
    confirmButton.focus()
  }

  function cancel(): void {
    isArmed = false
    applyArmedState()
    liveAnnouncer().announcePolite(currentProps.cancelledAnnouncement)
    armButton.focus()
  }

  function confirm(): void {
    // No disarm and no focus move: confirming removes the thing this action
    // belongs to, so both this component and its focus target are about to go.
    currentProps.onConfirm()
  }

  applyArmedState()

  const root = el('div', { class: 'flex shrink-0 items-center gap-1' }, [
    confirmButton,
    cancelButton,
    armButton,
  ])

  return {
    element: root,

    update(nextProps): void {
      currentProps = nextProps
      armButton.setAttribute('aria-label', nextProps.accessibleName)
      confirmButton.setAttribute('aria-label', nextProps.confirmAccessibleName)
      cancelButton.setAttribute('aria-label', nextProps.cancelAccessibleName)
    },

    destroy(): void {
      // Only click listeners are attached, and they live on this
      // component's own buttons — torn down automatically with the node.
    },
  }
}
