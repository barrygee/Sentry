import { classes, el, setAttribute, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import { ApiError, type DeviceStatus } from '../../api/client.js'
import { baseButton } from '../base/baseButton.js'
import { baseDialog } from '../base/baseDialog.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'
import {
  closeSerialFlashDialog,
  flashSerial,
  sdrsStore,
  serialFlashDialogDevice,
  type SdrsState,
} from '../../state/sdrsStore.js'
import { isDeviceIdle } from '../../utils/deviceState.js'
import { validateSerialClientSide } from '../../utils/serialValidation.js'

type FlashPhase = 'form' | 'submitting' | 'awaiting-outcome' | 'succeeded' | 'failed'

const NOTICE_BOX_CLASSES = 'rounded-rack px-4 py-3 text-[12.5px] leading-[1.55]'

/** Maps a thrown `ApiError`'s machine code to an operator-facing sentence — never surfaces a raw code. */
function humanizeFlashError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.detail?.code) {
      case 'device_busy':
        return 'This device became busy before the flash could start. Disable it and try again.'
      case 'serial_in_use':
        return 'That serial is already used by another device. Choose a different one.'
      case 'device_unidentified':
        return 'This device could not be resolved to a physical index. Replug it and try again.'
      case 'rtl_eeprom_unavailable':
        return 'The rtl_eeprom tool is unavailable on this Sentry host.'
      case 'flash_failed':
        return 'The write failed partway through. Check the device is still connected.'
      case 'invalid_serial':
        return 'That serial was rejected by the server — use 1-32 letters, numbers, hyphens or underscores.'
      default:
        return error.message
    }
  }
  return 'The request failed before it reached the server. Check the connection and try again.'
}

/**
 * Builds the `SerialFlashDialog`. Rendered once near the app root and driven
 * entirely by `sdrsStore.serialFlashDeviceId` — the invoking control (a
 * topology node, a device card, `SerialConflictBanner`) can be several
 * components away from wherever this dialog is mounted.
 *
 * The guarded EEPROM serial-flash flow (architecture §7.6, §11) — the most
 * dangerous action Sentry can take, since an interrupted `rtl_eeprom -s`
 * write can corrupt a dongle's USB descriptor. Every step says so plainly:
 * the exact serial is echoed back before commit, an explicit acknowledgement
 * gates the destructive button, the form is disabled unless the device is
 * idle, and progress after the `202 Accepted` is driven entirely by the SSE
 * `notice` stream — there is no polling and no synchronous result.
 */
export function serialFlashDialog(): Component<void> {
  const headingId = nextElementId('serial-flash-dialog-heading')
  const consequenceId = `${headingId}-consequence`

  let phase: FlashPhase = 'form'
  let serialDraft = ''
  let acknowledged = false
  let clientError: string | null = null
  let outcomeMessage: string | null = null
  let requiresReplug = false
  let requestStartedAtMs = 0
  let lastSeenDeviceId: string | null = null

  const heading = sectionHeading({ level: 2, children: [] })
  heading.element.id = headingId
  const introParagraph = el('p', { class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' }, [
    "Writes a permanent serial to this dongle's EEPROM via ",
    el('code', { class: 'font-mono' }, ['rtl_eeprom']),
    ". This is the most destructive action Sentry can take on hardware — an interrupted write can corrupt the device's USB descriptor.",
  ])
  const headerBlock = el('div', { class: 'flex flex-col gap-2' }, [heading.element, introParagraph])

  const notIdleMessage = el('p', { class: 'm-0' }, [])
  const notIdleNotice = noticeBox({ tone: 'danger', role: 'alert', children: [notIdleMessage] })

  const serialField = baseField({
    label: 'New serial',
    value: '',
    onChange: (value) => {
      serialDraft = value
      render()
    },
    hint: '1-32 letters, numbers, hyphens or underscores',
    error: null,
    disabled: true,
    onBlur: () => {
      clientError = validateSerialClientSide(serialDraft)
      render()
    },
  })

  const consequenceStrongDevice = el('strong', {}, [])
  const consequenceStrongSerial = el('strong', { class: 'font-mono' }, [])
  const consequenceParagraph = el('p', { attrs: { id: consequenceId }, class: 'm-0' }, [
    'This will stop ',
    consequenceStrongDevice,
    "'s pair (if running), then write ",
    consequenceStrongSerial,
    ' to its EEPROM. A physical replug is required afterwards before the new serial is visible.',
  ])
  const acknowledgeCheckbox = el('input', {
    attrs: { type: 'checkbox', 'aria-describedby': consequenceId, disabled: true },
    class: 'mt-0.5 h-4 w-4 shrink-0 accent-signal-ok',
    props: { checked: false },
    on: {
      change: () => {
        acknowledged = acknowledgeCheckbox.checked
        render()
      },
    },
  }) as HTMLInputElement
  const acknowledgeLabel = el('label', { class: 'flex items-start gap-2.5' }, [
    acknowledgeCheckbox,
    el('span', {}, ['I understand this writes to hardware and cannot be undone.']),
  ])
  const consequenceNotice = noticeBox({
    tone: 'warn',
    children: [consequenceParagraph, acknowledgeLabel],
  })

  const cancelButton = baseButton({
    variant: 'ghost',
    onClick: () => requestClose(),
    children: ['Cancel'],
  })
  const submitButton = baseButton({
    variant: 'danger',
    onClick: () => void submit(),
    children: ['Flash serial'],
  })
  setAttribute(submitButton.element, 'aria-describedby', consequenceId)
  const formActionsRow = el('div', { class: 'flex flex-wrap justify-end gap-2' }, [
    cancelButton.element,
    submitButton.element,
  ])

  const formBlock = el('div', { class: 'flex flex-col gap-4' }, [
    serialField.element,
    consequenceNotice.element,
    formActionsRow,
  ])

  // Persistent live regions, present for the whole lifetime of an open
  // dialog rather than freshly mounted per phase — only their text content
  // and visibility class change, so a screen reader that registered the
  // node before this phase began reliably hears the update.
  const statusRegion = el(
    'p',
    { attrs: { role: 'status', 'aria-atomic': 'true' }, class: 'sr-only' },
    [],
  )
  const alertRegion = el(
    'p',
    { attrs: { role: 'alert', 'aria-atomic': 'true' }, class: 'sr-only' },
    [],
  )

  const succeededCloseButton = baseButton({
    variant: 'primary',
    onClick: () => requestClose(),
    children: ['Close'],
  })
  const succeededActionsRow = el('div', { class: 'flex justify-end' }, [
    succeededCloseButton.element,
  ])

  const failedCloseButton = baseButton({
    variant: 'ghost',
    onClick: () => requestClose(),
    children: ['Close'],
  })
  const retryButton = baseButton({
    variant: 'primary',
    onClick: () => retry(),
    children: ['Try again'],
  })
  const failedActionsRow = el('div', { class: 'flex flex-wrap justify-end gap-2' }, [
    failedCloseButton.element,
    retryButton.element,
  ])

  const dialogBody = el('div', { class: 'flex flex-col gap-4' }, [
    headerBlock,
    notIdleNotice.element,
    formBlock,
    statusRegion,
    alertRegion,
    succeededActionsRow,
    failedActionsRow,
  ])

  const dialog = baseDialog({
    open: false,
    labelledBy: headingId,
    disableDismiss: false,
    onClose: () => requestClose(),
    children: [dialogBody],
  })

  function resetTransientState(): void {
    phase = 'form'
    serialDraft = ''
    acknowledged = false
    clientError = null
    outcomeMessage = null
    requiresReplug = false
  }

  function requestClose(): void {
    closeSerialFlashDialog()
  }

  function retry(): void {
    phase = 'form'
    outcomeMessage = null
    render()
  }

  function canSubmit(device: DeviceStatus): boolean {
    return (
      isDeviceIdle(device.state) &&
      phase !== 'submitting' &&
      phase !== 'awaiting-outcome' &&
      acknowledged &&
      validateSerialClientSide(serialDraft) === null
    )
  }

  async function submit(): Promise<void> {
    const device = serialFlashDialogDevice(sdrsStore.state)
    if (!device || !canSubmit(device)) {
      return
    }
    clientError = null
    phase = 'submitting'
    requestStartedAtMs = Date.now()
    render()
    try {
      const accepted = await flashSerial(device.device_id, serialDraft)
      requiresReplug = accepted.requires_replug
      phase = 'awaiting-outcome'
    } catch (error) {
      outcomeMessage = humanizeFlashError(error)
      phase = 'failed'
    }
    render()
  }

  function render(): void {
    renderFromState(sdrsStore.state)
  }

  // Drives the "awaiting-outcome" phase from live SSE notices: the backend
  // holds a per-device lock for the whole operation, so the first notice for
  // this device raised after the request was accepted is that operation's
  // outcome.
  function renderFromState(state: SdrsState): void {
    const device = serialFlashDialogDevice(state)

    // Reset all transient state whenever the dialog is retargeted at a new
    // device (including being closed, which sets `device` back to null).
    if ((device?.device_id ?? null) !== lastSeenDeviceId) {
      lastSeenDeviceId = device?.device_id ?? null
      resetTransientState()
    }

    const isOpen = device !== null
    const deviceLabel = device?.name || device?.device_id || ''
    const isDeviceIdleNow = device ? isDeviceIdle(device.state) : false
    const isBusy = phase === 'submitting' || phase === 'awaiting-outcome'

    if (phase === 'awaiting-outcome' && device) {
      const outcome = state.notices.find(
        (notice) => notice.device_id === device.device_id && notice.ts >= requestStartedAtMs,
      )
      if (outcome) {
        outcomeMessage = outcome.message
        phase = outcome.level === 'info' ? 'succeeded' : 'failed'
      }
    }

    heading.update({ level: 2, children: [`Flash a unique serial — ${deviceLabel}`] })

    setVisible(notIdleNotice.element, !isDeviceIdleNow)
    setText(
      notIdleMessage,
      device
        ? `This device is currently ${device.state}. Disable it and wait until it is idle before flashing.`
        : '',
    )

    const showForm = phase === 'form' || phase === 'submitting'
    setVisible(formBlock, showForm)
    if (showForm) {
      serialField.update({
        label: 'New serial',
        value: serialDraft,
        onChange: (value) => {
          serialDraft = value
          render()
        },
        hint: '1-32 letters, numbers, hyphens or underscores',
        error: clientError,
        disabled: !isDeviceIdleNow || isBusy,
        onBlur: () => {
          clientError = validateSerialClientSide(serialDraft)
          render()
        },
      })
      setText(consequenceStrongDevice, deviceLabel)
      setText(consequenceStrongSerial, serialDraft || '—')
      if (acknowledgeCheckbox.checked !== acknowledged) {
        acknowledgeCheckbox.checked = acknowledged
      }
      acknowledgeCheckbox.disabled = !isDeviceIdleNow || isBusy
      cancelButton.update({
        variant: 'ghost',
        disabled: isBusy,
        onClick: () => requestClose(),
        children: ['Cancel'],
      })
      submitButton.update({
        variant: 'danger',
        disabled: device ? !canSubmit(device) : true,
        onClick: () => void submit(),
        children: [phase === 'submitting' ? 'Starting…' : 'Flash serial'],
      })
    }

    const statusMessage =
      phase === 'awaiting-outcome'
        ? `Writing EEPROM — do not unplug ${deviceLabel}…`
        : phase === 'succeeded'
          ? `${outcomeMessage ?? 'Serial flashed successfully.'}${requiresReplug ? ' Replug the device to see the new serial.' : ''}`
          : ''
    const statusRegionVisible = phase === 'awaiting-outcome' || phase === 'succeeded'
    setText(statusRegion, statusMessage)
    statusRegion.className = statusRegionVisible
      ? phase === 'succeeded'
        ? classes(NOTICE_BOX_CLASSES, 'bg-signal-ok text-white')
        : 'text-[12.5px] leading-[1.55] text-signal-muted'
      : 'sr-only'

    const alertMessage = phase === 'failed' ? (outcomeMessage ?? '') : ''
    setText(alertRegion, alertMessage)
    alertRegion.className =
      phase === 'failed' ? classes(NOTICE_BOX_CLASSES, 'bg-signal-danger text-white') : 'sr-only'

    setVisible(succeededActionsRow, phase === 'succeeded')
    setVisible(failedActionsRow, phase === 'failed')

    dialog.update({
      open: isOpen,
      labelledBy: headingId,
      disableDismiss: isBusy,
      onClose: () => requestClose(),
      children: [dialogBody],
    })
  }

  const unsubscribe = watchStore(sdrsStore, renderFromState)

  return {
    element: dialog.element,

    update(): void {
      // Store-driven; nothing to do for a prop this component does not take.
    },

    destroy(): void {
      unsubscribe()
      dialog.destroy()
    },
  }
}
