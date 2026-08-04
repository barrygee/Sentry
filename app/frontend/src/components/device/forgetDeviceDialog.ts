import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { ApiError, type DeviceStatus } from '../../api/client.js'
import { deleteDevice } from '../../state/sdrsStore.js'
import { baseButton } from '../base/baseButton.js'
import { baseDialog } from '../base/baseDialog.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'

/**
 * The confirmation for discarding an absent device's persisted
 * configuration. Reuses `BaseDialog` for its focus-trap/Escape/focus-restore
 * behaviour rather than reimplementing modal semantics. Deleting is
 * recoverable in the sense that replugging the hardware re-detects it, but
 * the name/port/tuning defaults are genuinely gone, so the copy says that
 * plainly instead of a generic "are you sure".
 *
 * Rendered once near the app root and fed by whichever device the caller's
 * store currently has open (matching the `SerialFlashDialog` pattern) — the
 * invoking control lives inside `AbsentDeviceGroup`, several components away
 * from wherever this mounts.
 */
export interface ForgetDeviceDialogProps {
  device: DeviceStatus | null
  onClose: () => void
}

type ForgetPhase = 'confirm' | 'deleting' | 'failed'

/** Maps a thrown `ApiError`'s machine code to an operator-facing sentence, never a raw code. */
function humanizeForgetError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.detail?.code) {
      case 'device_present':
        return 'This device came back online before it could be forgotten — replugging during a flaky USB re-enumeration is exactly the race this guards against. It is no longer absent, so there is nothing to forget right now.'
      case 'unknown_device':
        return 'This device is already gone.'
      default:
        return error.message
    }
  }
  return 'The request failed before it reached the server. Check the connection and try again.'
}

/** Builds a `ForgetDeviceDialog`. `update` mutates the same panel in place. */
export function forgetDeviceDialog(
  props: ForgetDeviceDialogProps,
): Component<ForgetDeviceDialogProps> {
  let currentProps = props
  let phase: ForgetPhase = 'confirm'
  let errorMessage: string | null = null
  let lastDeviceId: string | null = props.device?.device_id ?? null

  const headingId = nextElementId('forget-dialog')
  const consequenceId = `${headingId}-consequence`

  function deviceLabel(): string {
    const device = currentProps.device
    return device?.name || device?.device_id || ''
  }

  function isBusy(): boolean {
    return phase === 'deleting'
  }

  function requestClose(): void {
    currentProps.onClose()
  }

  async function confirmForget(): Promise<void> {
    const device = currentProps.device
    if (!device || isBusy()) {
      return
    }
    phase = 'deleting'
    errorMessage = null
    render()
    try {
      await deleteDevice(device.device_id)
      // Success closes via `deleteDevice` itself (it clears the store's
      // open-dialog device), which flows back here as `device: null` on the
      // next `update`.
    } catch (error) {
      errorMessage = humanizeForgetError(error)
      phase = 'failed'
      render()
    }
  }

  // A `<div>`, not `<header>`: this dialog is teleported to `<body>`,
  // outside any sectioning root, so `<header>` here would register as a
  // second page-level "banner" landmark alongside the app header's.
  const heading = sectionHeading({ level: 2, children: [] })
  heading.element.id = headingId

  const consequenceLeadText = document.createTextNode('This discards ')
  const consequenceLabel = el('strong', {}, [])
  const consequenceTrailText = document.createTextNode(
    "'s saved name, output port and tuning defaults. It's recoverable in that replugging the hardware re-detects it as a fresh, unconfigured device — but nothing about how it was set up is kept.",
  )
  const consequenceParagraph = el(
    'p',
    { attrs: { id: consequenceId }, class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' },
    [consequenceLeadText, consequenceLabel, consequenceTrailText],
  )

  const headerDiv = el('div', { class: 'flex flex-col gap-2' }, [
    heading.element,
    consequenceParagraph,
  ])

  const errorParagraph = el('p', { class: 'm-0' }, [])
  const errorNotice = noticeBox({ tone: 'danger', role: 'alert', children: [errorParagraph] })

  const cancelButton = baseButton({
    variant: 'ghost',
    disabled: false,
    onClick: requestClose,
    children: ['Cancel'],
  })

  const confirmButton = baseButton({
    variant: 'danger',
    disabled: false,
    onClick: () => void confirmForget(),
    children: [],
  })
  confirmButton.element.setAttribute('aria-describedby', consequenceId)

  const actionsRow = el('div', { class: 'flex flex-wrap justify-end gap-2' }, [
    cancelButton.element,
    confirmButton.element,
  ])

  const dialog = baseDialog({
    open: props.device !== null,
    labelledBy: headingId,
    disableDismiss: isBusy(),
    onClose: requestClose,
    children: [headerDiv, errorNotice.element, actionsRow],
  })

  function render(): void {
    const label = deviceLabel()

    heading.update({ level: 2, children: [`Forget ${label}?`] })
    setText(consequenceLabel, label)

    setVisible(errorNotice.element, phase === 'failed')
    setText(errorParagraph, errorMessage ?? '')

    cancelButton.update({
      variant: 'ghost',
      disabled: isBusy(),
      onClick: requestClose,
      children: ['Cancel'],
    })

    setVisible(confirmButton.element, phase !== 'failed')
    confirmButton.update({
      variant: 'danger',
      disabled: isBusy(),
      onClick: () => void confirmForget(),
      children: [phase === 'deleting' ? 'Forgetting…' : 'Forget device'],
    })

    dialog.update({
      open: currentProps.device !== null,
      labelledBy: headingId,
      disableDismiss: isBusy(),
      onClose: requestClose,
      children: [headerDiv, errorNotice.element, actionsRow],
    })
  }

  render()

  return {
    element: dialog.element,

    update(nextProps): void {
      const nextDeviceId = nextProps.device?.device_id ?? null
      // Reset transient state whenever the dialog is retargeted (including
      // closed, which sets `device` back to null) so a stale error never
      // reappears for a different device.
      if (nextDeviceId !== lastDeviceId) {
        phase = 'confirm'
        errorMessage = null
      }
      lastDeviceId = nextDeviceId
      currentProps = nextProps
      render()
    },

    destroy(): void {
      dialog.destroy()
      heading.destroy()
      errorNotice.destroy()
      cancelButton.destroy()
      confirmButton.destroy()
    },
  }
}
