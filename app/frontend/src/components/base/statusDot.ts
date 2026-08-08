import { classes, el, setText } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { DEVICE_STATE_META } from '../../utils/deviceState.js'
import type { DeviceState } from '../../utils/deviceState.js'

export type { DeviceState }

/**
 * The shared state atom used everywhere a device's state appears (topology
 * lug, device card stripe, badge). Colour alone never carries meaning here:
 * each state also has a distinct glyph/shape, and the text label is either
 * visible or exposed to assistive tech via `visuallyHiddenLabel`
 * (architecture §9.4 — "colour is never the sole indicator").
 */
export interface StatusDotProps {
  state: DeviceState
  /** When true the text label is visually hidden but still in the accessibility tree. */
  visuallyHiddenLabel?: boolean
}

/** Builds a `StatusDot`. `update` mutates the same glyph/label elements in place. */
export function statusDot(props: StatusDotProps): Component<StatusDotProps> {
  const meta = DEVICE_STATE_META[props.state]

  const glyph = el(
    'span',
    {
      attrs: { 'aria-hidden': 'true' },
      class: classes('text-[10px]', 'leading-none', meta.textColorClass),
    },
    [meta.glyph],
  )
  const labelSpan = el('span', { class: props.visuallyHiddenLabel ? 'sr-only' : '' }, [meta.label])

  const root = el('span', { class: 'inline-flex items-center gap-1.5' }, [glyph, labelSpan])

  return {
    element: root,

    update(nextProps): void {
      const nextMeta = DEVICE_STATE_META[nextProps.state]
      glyph.className = classes('text-[10px]', 'leading-none', nextMeta.textColorClass)
      setText(glyph, nextMeta.glyph)
      labelSpan.className = nextProps.visuallyHiddenLabel ? 'sr-only' : ''
      setText(labelSpan, nextMeta.label)
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
