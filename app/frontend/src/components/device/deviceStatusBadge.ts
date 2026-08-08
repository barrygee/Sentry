import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { statusBadge } from '../base/statusBadge.js'
import { statusDot } from '../base/statusDot.js'
import type { DeviceState } from '../base/statusDot.js'

export type { DeviceState }

/**
 * A device's state, as an unfilled label beside a coloured glyph.
 *
 * The label's own tone stays neutral rather than tracking the state's colour:
 * `StatusDot` already carries that in the glyph, and colouring the word too
 * would say the same thing twice.
 */
export interface DeviceStatusBadgeProps {
  state: DeviceState
  reason?: string | null
}

function humanizeReason(reason: string): string {
  return reason.replaceAll('_', ' ')
}

/** Builds a `DeviceStatusBadge`. `update` mutates the same dot/label elements in place. */
export function deviceStatusBadge(
  props: DeviceStatusBadgeProps,
): Component<DeviceStatusBadgeProps> {
  const dot = statusDot({ state: props.state })

  const reasonSpan = el('span', { class: 'normal-case tracking-normal text-signal-muted' }, [])

  function applyReason(reason: string | null | undefined): void {
    const reasonText = reason ? humanizeReason(reason) : null
    setVisible(reasonSpan, reasonText !== null)
    setText(reasonSpan, reasonText !== null ? `· ${reasonText}` : '')
  }

  applyReason(props.reason)

  const badge = statusBadge({ tone: 'neutral', children: [dot.element, reasonSpan] })

  return {
    element: badge.element,

    update(nextProps): void {
      dot.update({ state: nextProps.state })
      applyReason(nextProps.reason)
      badge.update({ tone: 'neutral', children: [dot.element, reasonSpan] })
    },

    destroy(): void {
      dot.destroy()
      badge.destroy()
    },
  }
}
