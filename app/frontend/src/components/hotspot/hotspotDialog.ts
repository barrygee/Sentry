import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import type { HotspotState } from '../../api/client.js'
import { baseButton } from '../base/baseButton.js'
import { baseDialog } from '../base/baseDialog.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'
import {
  closeDialog,
  confirm as confirmHotspot,
  disable as disableHotspot,
  hotspotStore,
  isAwaitingConfirmation,
  refresh,
  save,
  type HotspotStoreState,
} from '../../state/hotspotStore.js'
import { hotspotClientList } from './hotspotClientList.js'
import type { HotspotClientListProps } from './hotspotClientList.js'
import { hotspotConfirmCountdown } from './hotspotConfirmCountdown.js'
import type { HotspotConfirmCountdownProps } from './hotspotConfirmCountdown.js'
import { hotspotForm } from './hotspotForm.js'
import type { HotspotFormActionsProps, HotspotFormProps } from './hotspotForm.js'
import { hotspotSetupHelp } from './hotspotSetupHelp.js'
import type { HotspotSetupHelpProps } from './hotspotSetupHelp.js'
import { hotspotStatusPanel } from './hotspotStatusPanel.js'
import type { HotspotStatusPanelProps } from './hotspotStatusPanel.js'

/**
 * The hotspot settings surface: status, form, confirmation window, leases.
 *
 * Rendered once near the app root and opened from the store, the same shape
 * `SerialFlashDialog` uses — the invoking control (the header gear) is
 * several components away from where the dialog is mounted, so a shared
 * store field is the only sensible source of truth for "is it open".
 *
 * Dismissal is suppressed while a request is in flight **and** while a
 * change is awaiting confirmation. A stray Escape during the confirmation
 * window would read as walking away from a network change that is already
 * live on the hardware, which is exactly when an operator most needs the
 * countdown in front of them.
 */

function blockedReason(state: HotspotState): string | null {
  if (!state.control_enabled) {
    return 'Hotspot control is switched off on this Sentry. Set SENTRY_HOTSPOT_CONTROL_ENABLED=true in its .env file and restart it.'
  }
  if (!state.auth_token_configured) {
    return 'Set an API access token (SENTRY_AUTH_TOKEN) before starting a hotspot. Without one, anyone who joins the network can reach this API with no credentials.'
  }
  if (!state.available) {
    return 'This Sentry cannot manage a WiFi hotspot: NetworkManager was not reachable. On the Pi, check that NetworkManager is running and that the D-Bus socket is mounted into the container.'
  }
  return null
}

/**
 * The confirmation deadline, or null when no change is on trial. Narrowed
 * here rather than at the call site so the countdown always receives a
 * plain `number`.
 */
function confirmDeadlineMs(state: HotspotState): number | null {
  if (!state.pending_confirmation) return null
  return state.confirm_deadline_ms ?? null
}

function buildHotspotFormActions(
  props: HotspotFormActionsProps,
): Component<HotspotFormActionsProps> {
  const saveButton = baseButton({
    type: 'submit',
    variant: 'primary',
    disabled: !props.canSubmit,
    children: [props.busy ? 'Saving…' : 'Save hotspot settings'],
  })
  // No Close here: the dialog owns one, unconditionally. This row is rendered
  // only when the hotspot is manageable, so a Close living here disappeared in
  // precisely the states that needed it.
  const root = el('div', { class: 'flex flex-wrap items-center gap-2' }, [saveButton.element])

  return {
    element: root,

    update(nextProps): void {
      saveButton.update({
        type: 'submit',
        variant: 'primary',
        disabled: !nextProps.canSubmit,
        children: [nextProps.busy ? 'Saving…' : 'Save hotspot settings'],
      })
    },

    destroy(): void {
      saveButton.destroy()
    },
  }
}

/**
 * Builds the `HotspotDialog`. Takes no props — it is rendered once near the
 * app root and driven entirely by `hotspotStore`.
 */
export function hotspotDialog(): Component<void> {
  const headingId = nextElementId('hotspot-dialog-heading')

  const heading = sectionHeading({ level: 2, children: ['WiFi hotspot'] })
  heading.element.id = headingId
  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'Run a WiFi network from this Sentry so clients can reach the SDRs with no LAN. This is in addition to how you connect today — nothing about your existing setup changes.',
  ])
  const headerBlock = el('div', { class: 'flex flex-col gap-2' }, [heading.element, introParagraph])

  // Both live regions stay mounted for the dialog's whole lifetime and only
  // change text. Mounting a live region that already contains its message
  // frequently announces nothing at all.
  const busyStatusRegion = el('p', { attrs: { role: 'status' }, class: 'sr-only' }, [])
  const errorAlertRegion = el('p', { attrs: { role: 'alert' }, class: 'sr-only' }, [])

  const loadingParagraph = el('p', { class: 'm-0 text-[12px] text-signal-muted' }, [
    'Loading hotspot settings…',
  ])

  const statusPanelSlot = el('div')
  const countdownSlot = el('div')
  const setupHelpSlot = el('div')
  const blockedNotice = noticeBox({ tone: 'warn', role: 'alert', children: [] })
  const advertisedHostNotice = noticeBox({
    tone: 'warn',
    role: 'status',
    children: [
      'This Sentry publishes a fixed address to Sentinel (SENTRY_ADVERTISED_HOST), which is not the hotspot’s address. Clients joining the hotspot should use the address shown above instead.',
    ],
  })
  const errorNotice = noticeBox({ tone: 'danger', role: 'status', children: [] })
  const formSlot = el('div')
  const clientListSlot = el('div')

  const contentBlock = el('div', { class: 'flex flex-col gap-6' }, [
    statusPanelSlot,
    countdownSlot,
    setupHelpSlot,
    blockedNotice.element,
    advertisedHostNotice.element,
    errorNotice.element,
    formSlot,
    clientListSlot,
  ])

  // Outside `contentBlock`, and outside the form, so it exists in every state.
  // It used to live in the form's action row, which is rendered only when the
  // hotspot is manageable — so the states that render no form (control disabled
  // in .env, no auth token, NetworkManager unreachable) offered no way out at
  // all. Those are exactly the states an operator lands in by accident and most
  // needs to leave. `Escape` still worked, but a modal whose only dismissal is
  // an invisible keystroke is not dismissible in any sense that matters.
  const dismissButton = baseButton({
    variant: 'ghost',
    onClick: () => closeDialog(),
    children: ['Close'],
  })

  const dialogBody = el('div', { class: 'flex max-h-[80vh] flex-col gap-6 overflow-y-auto' }, [
    headerBlock,
    busyStatusRegion,
    errorAlertRegion,
    loadingParagraph,
    contentBlock,
    el('div', {}, [dismissButton.element]),
  ])

  const dialog = baseDialog({
    open: false,
    labelledBy: headingId,
    disableDismiss: false,
    onClose: () => closeDialog(),
    children: [dialogBody],
  })

  let statusPanel: Component<HotspotStatusPanelProps> | null = null
  let confirmCountdown: Component<HotspotConfirmCountdownProps> | null = null
  let setupHelp: Component<HotspotSetupHelpProps> | null = null
  let form: Component<HotspotFormProps> | null = null
  let clientList: Component<HotspotClientListProps> | null = null

  let previousDialogOpen = false

  function render(storeState: HotspotStoreState): void {
    const isBusy = storeState.phase === 'submitting'
    const state = storeState.state

    setText(busyStatusRegion, isBusy ? 'Applying hotspot settings.' : '')
    setText(
      errorAlertRegion,
      storeState.phase === 'failed' && storeState.errorMessage ? storeState.errorMessage : '',
    )

    setVisible(loadingParagraph, state === null)
    setVisible(contentBlock, state !== null)

    if (state !== null) {
      if (!statusPanel) {
        statusPanel = hotspotStatusPanel({ state })
        statusPanelSlot.appendChild(statusPanel.element)
      } else {
        statusPanel.update({ state })
      }

      const deadline = confirmDeadlineMs(state)
      setVisible(countdownSlot, deadline !== null)
      if (deadline !== null) {
        const countdownProps: HotspotConfirmCountdownProps = {
          deadlineMs: deadline,
          busy: isBusy,
          onConfirm: () => void confirmHotspot(),
          onDiscard: () => void disableHotspot(true),
        }
        if (!confirmCountdown) {
          confirmCountdown = hotspotConfirmCountdown(countdownProps)
          countdownSlot.appendChild(confirmCountdown.element)
        } else {
          confirmCountdown.update(countdownProps)
        }
      }

      const reason = blockedReason(state)
      const showSetupHelp = !state.control_enabled || !state.auth_token_configured
      setVisible(setupHelpSlot, showSetupHelp)
      if (showSetupHelp) {
        const setupHelpProps: HotspotSetupHelpProps = {
          controlEnabled: state.control_enabled,
          authTokenConfigured: state.auth_token_configured,
        }
        if (!setupHelp) {
          setupHelp = hotspotSetupHelp(setupHelpProps)
          setupHelpSlot.appendChild(setupHelp.element)
        } else {
          setupHelp.update(setupHelpProps)
        }
      }

      const showBlockedNotice = !showSetupHelp && reason !== null
      setVisible(blockedNotice.element, showBlockedNotice)
      if (showBlockedNotice) {
        blockedNotice.update({ tone: 'warn', role: 'alert', children: [reason ?? ''] })
      }

      setVisible(
        advertisedHostNotice.element,
        state.warnings.includes('advertised_host_overrides_gateway'),
      )

      const showErrorNotice = storeState.phase === 'failed' && storeState.errorMessage !== null
      setVisible(errorNotice.element, showErrorNotice)
      if (showErrorNotice) {
        errorNotice.update({
          tone: 'danger',
          role: 'status',
          children: [storeState.errorMessage ?? ''],
        })
      }

      const showForm = reason === null
      setVisible(formSlot, showForm)
      if (showForm) {
        const formProps: HotspotFormProps = {
          state,
          interfaces: storeState.interfaces,
          busy: isBusy,
          onSubmit: (config) => void save(config),
          actions: buildHotspotFormActions,
        }
        if (!form) {
          form = hotspotForm(formProps)
          formSlot.appendChild(form.element)
        } else {
          form.update(formProps)
        }
      }

      const showClientList = state.configured
      setVisible(clientListSlot, showClientList)
      if (showClientList) {
        const clientListProps: HotspotClientListProps = { clients: storeState.clients }
        if (!clientList) {
          clientList = hotspotClientList(clientListProps)
          clientListSlot.appendChild(clientList.element)
        } else {
          clientList.update(clientListProps)
        }
      }
    }

    // The button mirrors `disableDismiss` rather than being unconditionally
    // enabled: suppression during a request, and during the confirmation
    // window, is deliberate (see this module's docstring). A Close that stayed
    // live would walk an operator away from a network change already applied to
    // the hardware — the precise thing the countdown exists to prevent.
    const dismissSuppressed = isBusy || isAwaitingConfirmation(storeState)
    dismissButton.update({
      variant: 'ghost',
      disabled: dismissSuppressed,
      onClick: () => closeDialog(),
      children: ['Close'],
    })

    dialog.update({
      open: storeState.dialogOpen,
      labelledBy: headingId,
      disableDismiss: dismissSuppressed,
      onClose: () => closeDialog(),
      children: [dialogBody],
    })

    // Refetch whenever the dialog opens so a hotspot changed elsewhere (or
    // rolled back while the tab was closed) is never shown stale.
    if (storeState.dialogOpen && !previousDialogOpen) {
      void refresh()
    }
    previousDialogOpen = storeState.dialogOpen
  }

  const unsubscribe = watchStore(hotspotStore, render)

  return {
    element: dialog.element,

    update(): void {
      // Store-driven; nothing to do for a prop this component does not take.
    },

    destroy(): void {
      unsubscribe()
      statusPanel?.destroy()
      confirmCountdown?.destroy()
      setupHelp?.destroy()
      form?.destroy()
      clientList?.destroy()
      blockedNotice.destroy()
      advertisedHostNotice.destroy()
      errorNotice.destroy()
      dialog.destroy()
    },
  }
}
