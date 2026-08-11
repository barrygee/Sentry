import { el, setText } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { noticeBox } from '../base/noticeBox.js'
import { syncChildren } from '../base/childrenSync.js'

/**
 * The "this will cut this Sentry off the network" warning, and the
 * acknowledgement that unlocks it.
 *
 * On a Pi with one radio, raising an access point on the interface that
 * carries the uplink tears that connection down — including, quite possibly,
 * the one carrying the request being made right now. The server refuses
 * outright until `confirm_uplink_loss` is set, so this is the control that
 * sets it.
 *
 * Deliberately a plain checkbox gate rather than a "proceed anyway" button:
 * copies the guarded pattern `SerialFlashSection` uses for the EEPROM write,
 * the app's other irreversible-feeling action, so the same shape means the
 * same thing in both places.
 */
export interface HotspotUplinkWarningProps {
  value: boolean
  onChange: (value: boolean) => void
  /** The interface that will be taken over, e.g. "wlan0". */
  interfaceName: string
  /** The network it is currently joined to, when known. */
  stationSsid?: string | null
  disabled?: boolean
}

function firstParagraphChildren(props: HotspotUplinkWarningProps): Child[] {
  return [
    el('strong', { class: 'font-semibold' }, [
      `${props.interfaceName} is this Sentry’s own connection`,
    ]),
    props.stationSsid ? ` to ${props.stationSsid}` : null,
    '. Starting the hotspot on it will disconnect that link — including this browser, if you are using the same network.',
  ]
}

/** Builds a `HotspotUplinkWarning`. `update` mutates the same notice in place. */
export function hotspotUplinkWarning(
  props: HotspotUplinkWarningProps,
): Component<HotspotUplinkWarningProps> {
  let currentProps = props

  const firstParagraph = el('p', { class: 'm-0' }, firstParagraphChildren(props))
  const secondParagraph = el('p', { class: 'm-0' }, [
    'If it does not come back, Sentry undoes the change by itself after the confirmation window. Do the first run over Ethernet where you can.',
  ])

  const checkbox = el('input', {
    attrs: { type: 'checkbox', disabled: props.disabled ?? false },
    class: 'h-4 w-4 shrink-0 accent-signal-danger',
    props: { checked: props.value },
    on: { change: () => currentProps.onChange(checkbox.checked) },
  }) as HTMLInputElement

  const checkboxCaption = el('span', { class: 'text-[12px] leading-[1.6]' }, [
    `I understand this will disconnect ${props.interfaceName}`,
  ])

  // Nesting alone associates the label — matching `SerialFlashSection`'s
  // acknowledgement checkbox. Adding a `for`/`id` pair on top of the nesting
  // would leave the control with no accessible name at all.
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
