import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import type { HotspotState } from '../../api/client.js'
import { baseButton } from '../base/baseButton.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { disclosureSection } from '../base/disclosureSection.js'
import {
  confirm as confirmHotspot,
  disable as disableHotspot,
  hotspotStore,
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
 * A section of the Settings view rather than a modal. It was a dialog, which
 * suited a control reached from a header icon but suited nothing else: the
 * panel is long, frequently read rather than acted on, and its confirmation
 * countdown wants to stay visible while an operator checks whether their WiFi
 * still works — none of which a modal is good at.
 *
 * The countdown's guard did not survive the move unchanged. A modal could
 * refuse to close; a section cannot refuse to be navigated away from, so the
 * guard moved to the navigation itself (`main.ts`) rather than being dropped.
 * Walking away mid-countdown abandons a network change already applied to the
 * hardware, which is the one thing the countdown exists to prevent.
 */

function blockedReason(state: HotspotState): string | null {
  if (!state.control_enabled) {
    return 'Hotspot control is switched off on this Sentry. Turn it on below.'
  }
  if (!state.auth_token_configured) {
    return 'Set a Sentry controller password before starting a hotspot. Without one, anyone who joins the network can reach this controller with no credentials.'
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
    variant: 'on-bright',
    disabled: !props.canSubmit,
    children: [props.busy ? 'Saving…' : 'Save hotspot settings'],
  })
  // No Close here: the dialog owns one, unconditionally. This row is rendered
  // only when the hotspot is manageable, so a Close living here disappeared in
  // precisely the states that needed it.
  const root = el('div', { class: 'flex flex-wrap items-center justify-end gap-2' }, [
    saveButton.element,
  ])

  return {
    element: root,

    update(nextProps): void {
      saveButton.update({
        type: 'submit',
        variant: 'on-bright',
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
 * Builds the hotspot settings section. Takes no props — it is mounted once by
 * the Settings view and driven entirely by `hotspotStore`.
 */
export function hotspotPanel(): Component<void> {
  const headingId = nextElementId('hotspot-panel-heading')

  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'Run a WiFi network from this Sentry so clients can reach the SDRs with no LAN.',
  ])

  // The form mounts its toggle row here — a line of its own beneath the title
  // and its description, rather than competing with the heading for the same
  // line. Full width so the row's own `justify-end` can hold them right.
  const headerControlsHost = el('div')

  const headerBlock = el('div', { class: 'flex flex-col gap-4' }, [
    introParagraph,
    headerControlsHost,
  ])

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
  // The form mounts its countdown slot and action row here — below the lease
  // list, which is not part of the form. Empty until the form exists, and the
  // form removes its contents again on destroy.
  const actionsHost = el('div')

  const contentBlock = el('div', { class: 'flex flex-col gap-6' }, [
    statusPanelSlot,
    setupHelpSlot,
    blockedNotice.element,
    advertisedHostNotice.element,
    errorNotice.element,
    formSlot,
    clientListSlot,
    actionsHost,
  ])

  // The box collapses from its own title. `defaultOpen` because a settings box
  // that starts shut hides the thing the operator navigated here for — the
  // arrow is for putting a finished box away, not for making them open it.
  const disclosure = disclosureSection({
    label: ['WiFi hotspot'],
    headingLevel: 2,
    headingId,
    tone: 'panel',
    defaultOpen: true,
    isBoxTitle: true,
    // Before the disclosure, the heading and its description were a `gap-2` pair;
    // a `<summary>` sits flush against the body, so that gap is restored here.
    bodyClass: 'flex flex-col gap-6 pt-2',
    children: [headerBlock, busyStatusRegion, errorAlertRegion, loadingParagraph, contentBlock],
  })

  // No Close control, and no height cap: as a section this scrolls with the
  // page rather than inside its own box, and there is nothing to dismiss.
  const panelRoot = el(
    'section',
    {
      class: 'flex flex-col bg-ground-panel p-card',
      attrs: { 'aria-labelledby': headingId },
    },
    [disclosure.element],
  )

  let statusPanel: Component<HotspotStatusPanelProps> | null = null
  let confirmCountdown: Component<HotspotConfirmCountdownProps> | null = null
  let setupHelp: Component<HotspotSetupHelpProps> | null = null
  let form: Component<HotspotFormProps> | null = null
  let clientList: Component<HotspotClientListProps> | null = null

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
      // Nothing to report while control is switched off: every readout in the
      // status panel is hidden in that state, leaving an empty block that still
      // took its height and its `gap-6` — the gap between the heading and the
      // notice below was mostly this.
      setVisible(statusPanelSlot, state.control_enabled)

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
        // The command's own output, when the server sent one. It is the only
        // thing that says *why* NetworkManager refused, and it is already
        // scrubbed of the hotspot passphrase — printed verbatim rather than
        // summarised, because a paraphrase of an nmcli error is a guess.
        //
        // Read from the store's `errorCommandOutput` (taken off the failing
        // response) and not from `state.last_error`: on a failed request the
        // store still holds the *pre-request* state, whose `last_error` is
        // whatever it was before. That was almost always `null`, so this
        // rendered nothing at exactly the moment it was needed and left the
        // message telling the operator to go and read the Pi's logs instead.
        const commandOutput = storeState.errorCommandOutput
        errorNotice.update({
          tone: 'danger',
          role: 'status',
          children:
            commandOutput === null
              ? [storeState.errorMessage ?? '']
              : [
                  el('p', { class: 'm-0' }, [storeState.errorMessage ?? '']),
                  el(
                    'pre',
                    {
                      class:
                        'm-0 mt-2 overflow-x-auto whitespace-pre-wrap break-words font-tabular text-[11px] leading-[1.6] opacity-90',
                    },
                    [commandOutput],
                  ),
                ],
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
          // The countdown belongs beside the button that caused it. At the top
          // of the panel it sat a full screen away from the control an operator
          // had just used, and its two actions read as unrelated to the form.
          beforeActions: [countdownSlot],
          headerControlsHost,
          actionsHost,
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
  }

  const unsubscribe = watchStore(hotspotStore, render)

  return {
    element: panelRoot,

    update(): void {
      // Store-driven; nothing to do for a prop this component does not take.
    },

    destroy(): void {
      unsubscribe()
      disclosure.destroy()
      statusPanel?.destroy()
      confirmCountdown?.destroy()
      setupHelp?.destroy()
      form?.destroy()
      clientList?.destroy()
      blockedNotice.destroy()
      advertisedHostNotice.destroy()
      errorNotice.destroy()
    },
  }
}
