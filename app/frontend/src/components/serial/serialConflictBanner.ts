import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import type { SerialConflictDevice } from '../../state/sdrsStore.js'
import { baseButton } from '../base/baseButton.js'
import { confirmIconAction } from '../base/confirmIconAction.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * Surfaces a duplicate-serial conflict (architecture §5.1 tier 3, and the
 * `409 serial_in_use` guard on the EEPROM flash flow §7.6): two present
 * devices report the same serial, so neither can be trusted as a
 * persistence key until the operator flashes a unique one.
 *
 * This is the SDR-level summary of the same condition
 * `NeedsIdentificationNotice` already surfaces inline on each affected
 * card — one banner per duplicate serial, offering the destructive action
 * directly against whichever of the conflicting devices the operator
 * chooses to re-identify.
 */
export interface SerialConflictBannerProps {
  serial: string
  conflictingDevices: SerialConflictDevice[]
  onDismiss: () => void
  onRequestSerialFlash: (deviceId: string) => void
}

interface FlashButtonRowProps {
  device: SerialConflictDevice
  onRequestSerialFlash: (deviceId: string) => void
}

function flashButtonRow(props: FlashButtonRowProps): Component<FlashButtonRowProps> {
  let currentProps = props
  const button = baseButton({
    variant: 'inverse',
    onClick: () => currentProps.onRequestSerialFlash(currentProps.device.deviceId),
    children: [`Flash serial — ${props.device.label}`],
  })
  const root = el('li', {}, [button.element])

  return {
    element: root,

    update(nextProps): void {
      currentProps = nextProps
      button.update({
        variant: 'inverse',
        onClick: () => currentProps.onRequestSerialFlash(currentProps.device.deviceId),
        children: [`Flash serial — ${nextProps.device.label}`],
      })
    },

    destroy(): void {
      button.destroy()
    },
  }
}

/** Builds a `SerialConflictBanner`. `update` mutates the same notice in place. */
export function serialConflictBanner(
  props: SerialConflictBannerProps,
): Component<SerialConflictBannerProps> {
  let currentProps = props

  const conflictSerialSpan = el('span', { class: 'font-mono' }, [props.serial])
  const conflictingLabelsSpan = el('span', {}, [])
  const mainParagraph = el('p', { class: 'm-0' }, [
    'Serial conflict — ',
    conflictSerialSpan,
    ' is reported by more than one present device',
    conflictingLabelsSpan,
    '. Neither can be remembered across a reboot until one is given a unique serial.',
  ])

  // What the buttons below actually do. Without this the only clue is the
  // word "flash", and the operator has to open a dialog about an
  // irreversible hardware write to find out what it means.
  const consequenceParagraph = el('p', { class: 'm-0 text-white/85' }, [
    "Flashing writes a new permanent serial to the chosen dongle's memory chip. It stops that dongle while it runs, and the dongle must be unplugged and reconnected before the new serial takes effect. You'll be asked to confirm first.",
  ])

  const flashList = el('ul', { class: 'm-0 flex list-none flex-wrap gap-2 p-0' })
  const flashListController = keyedList<FlashButtonRowProps, string>(
    flashList,
    flashButtonRow,
    (rowProps) => rowProps.device.deviceId,
  )

  const leftColumn = el('div', { class: 'flex flex-col gap-3' }, [
    mainParagraph,
    consequenceParagraph,
    flashList,
  ])

  const dismissAction = confirmIconAction({
    accessibleName: `Dismiss serial conflict for ${props.serial}`,
    confirmAccessibleName: 'Confirm dismiss serial conflict',
    cancelAccessibleName: 'Cancel dismissing serial conflict',
    armedAnnouncement: 'Confirm dismissing this serial conflict, or cancel.',
    cancelledAnnouncement: 'Dismissing serial conflict cancelled.',
    onConfirm: () => currentProps.onDismiss(),
  })
  dismissAction.element.classList.add('self-start')

  const row = el(
    'div',
    { class: 'flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4' },
    [leftColumn, dismissAction.element],
  )

  const notice = noticeBox({ tone: 'danger', role: 'alert', children: [row] })

  function render(nextProps: SerialConflictBannerProps): void {
    setText(conflictSerialSpan, nextProps.serial)
    const hasConflicts = nextProps.conflictingDevices.length > 0
    setText(
      conflictingLabelsSpan,
      hasConflicts
        ? ` (${nextProps.conflictingDevices.map((device) => device.label).join(', ')})`
        : '',
    )
    setVisible(consequenceParagraph, hasConflicts)
    setVisible(flashList, hasConflicts)
    flashListController.update(
      nextProps.conflictingDevices.map((device) => ({
        device,
        onRequestSerialFlash: nextProps.onRequestSerialFlash,
      })),
    )
    dismissAction.update({
      accessibleName: `Dismiss serial conflict for ${nextProps.serial}`,
      confirmAccessibleName: 'Confirm dismiss serial conflict',
      cancelAccessibleName: 'Cancel dismissing serial conflict',
      armedAnnouncement: 'Confirm dismissing this serial conflict, or cancel.',
      cancelledAnnouncement: 'Dismissing serial conflict cancelled.',
      onConfirm: () => currentProps.onDismiss(),
    })
  }

  render(props)

  return {
    element: notice.element,

    update(nextProps): void {
      currentProps = nextProps
      render(nextProps)
    },

    destroy(): void {
      flashListController.destroy()
      dismissAction.destroy()
      notice.destroy()
    },
  }
}
