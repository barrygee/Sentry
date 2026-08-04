import { el } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { baseButton } from '../base/baseButton.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * Shown for a tier-3 identity device (architecture §5.1): two present
 * dongles collapse to the same identity key, so nothing is persisted or
 * spawned until the operator flashes a unique serial.
 */
export interface NeedsIdentificationNoticeProps {
  onRequestSerialFlash: () => void
}

/** Builds a `NeedsIdentificationNotice`. `update` mutates the same box/button in place. */
export function needsIdentificationNotice(
  props: NeedsIdentificationNoticeProps,
): Component<NeedsIdentificationNoticeProps> {
  let currentProps = props

  // `role="status"` wraps only the announcement text — the button that
  // follows is interactive chrome, not part of what should be read out
  // when this notice first appears (architecture §9.4).
  const paragraph = el('p', { attrs: { role: 'status' }, class: 'm-0' }, [
    "Needs identification — this dongle's factory serial isn't unique enough to remember it across reboots.",
  ])

  const button = baseButton({
    variant: 'on-bright',
    onClick: () => currentProps.onRequestSerialFlash(),
    children: ['Give this dongle a unique serial'],
  })
  button.element.classList.add('self-start')

  const box = noticeBox({ tone: 'warn', children: [paragraph, button.element] })

  return {
    element: box.element,

    update(nextProps): void {
      currentProps = nextProps
    },

    destroy(): void {
      button.destroy()
      box.destroy()
    },
  }
}
