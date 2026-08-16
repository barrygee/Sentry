import { el, setText } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { noticeBox } from '../base/noticeBox.js'
import { syncChildren } from '../base/childrenSync.js'

/**
 * The "this will take this Sentry off your network" warning, and the
 * acknowledgement that unlocks it.
 *
 * A near-twin of `hotspotUplinkWarning`, kept separate rather than
 * parameterised because the *content* is what differs, not the shape: on this
 * Pi the wired port is not merely one candidate that might happen to be the
 * uplink — it usually is the uplink, and sharing it is a certainty rather than
 * a risk. The wording says so, and the escape hatch it points at is the
 * hotspot rather than "plug in Ethernet", which would be the port being taken.
 *
 * Deliberately a plain checkbox gate rather than a "proceed anyway" button,
 * copying the guarded pattern `SerialFlashSection` and the hotspot warning both
 * use, so the same shape means the same thing everywhere in the app.
 */
export interface WiredUplinkWarningProps {
  value: boolean
  onChange: (value: boolean) => void
  /** The port that will be taken over, e.g. "eth0". */
  interfaceName: string
  /** The connection it currently carries, when known. */
  activeConnectionName?: string | null
  disabled?: boolean
}

function firstParagraphChildren(props: WiredUplinkWarningProps): Child[] {
  return [
    el('strong', { class: 'font-semibold' }, [
      `${props.interfaceName} is this Sentry’s own connection`,
    ]),
    props.activeConnectionName ? ` (${props.activeConnectionName})` : null,
    '. Sharing it stops this Sentry being a client of your network and makes it the network — so its current address goes away, and this browser loses the Pi if you are reaching it over that cable.',
  ]
}

/** Builds a `WiredUplinkWarning`. `update` mutates the same notice in place. */
export function wiredUplinkWarning(
  props: WiredUplinkWarningProps,
): Component<WiredUplinkWarningProps> {
  let currentProps = props

  const firstParagraph = el('p', { class: 'm-0' }, firstParagraphChildren(props))
  const secondParagraph = el('p', { class: 'm-0' }, [
    'If you cannot confirm from the other side, Sentry undoes the change by itself after the confirmation window and puts the port back on your network. Have the hotspot running, or a keyboard and monitor to hand, before you start.',
  ])

  const checkbox = el('input', {
    attrs: { type: 'checkbox', disabled: props.disabled ?? false },
    class: 'checkbox-plain',
    props: { checked: props.value },
    on: { change: () => currentProps.onChange(checkbox.checked) },
  }) as HTMLInputElement

  const checkboxCaption = el('span', { class: 'text-[12px] leading-[1.6]' }, [
    `I understand this will disconnect ${props.interfaceName}`,
  ])

  // Nesting alone associates the label — matching the hotspot's equivalent and
  // `SerialFlashSection`'s acknowledgement. Adding a `for`/`id` pair on top of
  // the nesting would leave the control with no accessible name at all.
  const label = el('label', { class: 'flex min-h-[44px] cursor-pointer items-center gap-3' }, [
    checkbox,
    checkboxCaption,
  ])

  const wrapper = el('div', { class: 'flex flex-col gap-3' }, [
    firstParagraph,
    secondParagraph,
    label,
  ])

  const notice = noticeBox({ tone: 'danger', role: 'alert', children: [wrapper] })

  return {
    element: notice.element,

    update(nextProps): void {
      currentProps = nextProps
      syncChildren(firstParagraph, firstParagraphChildren(nextProps))
      setText(checkboxCaption, `I understand this will disconnect ${nextProps.interfaceName}`)
      if (checkbox.checked !== nextProps.value) {
        checkbox.checked = nextProps.value
      }
      checkbox.disabled = nextProps.disabled ?? false
      notice.update({ tone: 'danger', role: 'alert', children: [wrapper] })
    },

    destroy(): void {
      notice.destroy()
    },
  }
}
