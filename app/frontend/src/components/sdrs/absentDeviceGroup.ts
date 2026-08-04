import { el } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import type { DeviceStatus } from '../../api/client.js'
import { chevronIcon } from '../base/chevronIcon.js'
import { panelStack } from '../base/panelStack.js'
import { sdrDeviceCard } from '../device/sdrDeviceCard.js'
import type { SdrDeviceCardProps } from '../device/sdrDeviceCard.js'

/**
 * Collapsible, visually de-emphasised group for configured devices that are
 * not currently plugged in ("ghosts" — Sentry keys unidentified dongles by
 * USB topology path, so a re-enumerated or moved dongle leaves its old
 * configuration behind as an absent record). Kept structurally separate from
 * the present-device stack, behind its own disclosure rather than colour
 * alone, so an operator scanning the page can tell instantly what hardware is
 * actually attached — and collapsed by default so several accumulated ghosts
 * never dominate the page.
 *
 * The group has no fill of its own. It carried a faint wash (which replaced
 * an earlier dashed outline), but a tinted container wrapping white device
 * boxes only banded the canvas above and below them — reading as a stray
 * panel edge rather than as a group. De-emphasis comes entirely from the
 * muted summary and description, and from the disclosure being closed by
 * default.
 *
 * The summary sits on the settings vocabulary: a muted group label (matching
 * "USB Topology" and "Devices" above it), with the ghosts inside laid out in
 * their own `PanelStack`, so an expanded group looks like the live grid with
 * the colour drained out of it rather than like a different kind of list.
 */
export interface AbsentDeviceGroupProps {
  devices: DeviceStatus[]
  onRequestSerialFlash: (deviceId: string) => void
}

const SUMMARY_CLASSES =
  'flex min-h-[44px] cursor-pointer list-none items-center gap-2 rounded-rack py-3 font-sans text-[10px] font-semibold uppercase tracking-control text-signal-muted transition-colors hover:text-ink-primary [&::-webkit-details-marker]:hidden'

/** Builds an `AbsentDeviceGroup`. `update` mutates the same summary count and card list in place; the disclosure's open/closed state is the browser's own, mirrored from the element rather than driven by props. */
export function absentDeviceGroup(
  props: AbsentDeviceGroupProps,
): Component<AbsentDeviceGroupProps> {
  let currentProps = props

  const chevron = chevronIcon({ open: false })
  chevron.element.classList.add('ml-auto')

  const summaryLabel = document.createTextNode('')
  const summary = el('summary', { class: SUMMARY_CLASSES }, [summaryLabel, chevron.element])

  const description = el('p', { class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' }, [
    'Not currently plugged in. Replugging the hardware re-detects it; forgetting one discards its saved name, port and tuning defaults.',
  ])

  const stack = panelStack({ children: [] })
  const cardList = keyedList<SdrDeviceCardProps, string>(
    stack.element,
    sdrDeviceCard,
    (cardProps) => cardProps.device.device_id,
  )

  const body = el('div', { class: 'flex flex-col gap-4 pb-card' }, [description, stack.element])

  // `<details open>` is a DOM attribute the browser toggles itself, so it is
  // mirrored here off the element's own `toggle` event rather than driven by
  // a prop. That keeps the native disclosure behaviour (including keyboard
  // and find-in-page expansion) authoritative, with the chevron following it.
  const details = el(
    'details',
    {
      class: 'group mt-2 rounded-rack',
      on: {
        toggle: (event) => {
          chevron.update({ open: (event.target as HTMLDetailsElement).open })
        },
      },
    },
    [summary, body],
  )

  function render(): void {
    summaryLabel.data = `Absent devices — configuration kept (${currentProps.devices.length})`
    cardList.update(
      currentProps.devices.map((device): SdrDeviceCardProps => ({
        device,
        onRequestSerialFlash: currentProps.onRequestSerialFlash,
      })),
    )
  }

  render()

  return {
    element: details,

    update(nextProps): void {
      currentProps = nextProps
      render()
    },

    destroy(): void {
      chevron.destroy()
      cardList.destroy()
    },
  }
}
