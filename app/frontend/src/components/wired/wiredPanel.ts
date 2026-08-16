import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import type { WiredShareState } from '../../api/client.js'
import { baseButton } from '../base/baseButton.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { disclosureSection } from '../base/disclosureSection.js'
import {
  confirm as confirmWired,
  disable as disableWired,
  enable as enableWired,
  refresh,
  save,
  wiredStore,
  type WiredStoreState,
} from '../../state/wiredStore.js'
import { wiredClientList } from './wiredClientList.js'
import type { WiredClientListProps } from './wiredClientList.js'
import { wiredConfirmCountdown } from './wiredConfirmCountdown.js'
import type { WiredConfirmCountdownProps } from './wiredConfirmCountdown.js'
import { wiredForm } from './wiredForm.js'
import type { WiredFormActionsProps, WiredFormProps } from './wiredForm.js'
import { wiredStatusPanel } from './wiredStatusPanel.js'
import type { WiredStatusPanelProps } from './wiredStatusPanel.js'

/**
 * The wired-sharing settings surface: status, form, confirmation window, leases.
 *
 * Deliberately built to the same shape as `hotspotPanel`, and sits directly
 * beneath it in Settings. They are the two answers to one question — "how does
 * a machine with no route to my LAN reach this Sentry" — so an operator should
 * be able to read one having understood the other, and the panels differing in
 * layout would make that harder for no gain.
 *
 * Collapsed by default, unlike nothing else on the page: wired sharing is the
 * rarer of the two, set once when it is needed and then left alone.
 */

function blockedReason(state: WiredShareState): string | null {
  if (!state.control_enabled) {
    return 'Host network control is switched off on this Sentry. Turn it on in the WiFi hotspot box above — the same switch covers the Ethernet port.'
  }
  if (!state.console_password_set) {
    return 'Set a Sentry controller password before sharing an Ethernet port. Without one, anyone who plugs in a cable can reach this controller with no credentials.'
  }
  if (!state.available) {
    return 'This Sentry cannot share an Ethernet port: NetworkManager was not reachable. On the Pi, check that NetworkManager is running and that the D-Bus socket is mounted into the container.'
  }
  return null
}

/**
 * The confirmation deadline, or null when no change is on trial. Narrowed here
 * rather than at the call site so the countdown always receives a plain number.
 */
function confirmDeadlineMs(state: WiredShareState): number | null {
  if (!state.pending_confirmation) return null
  return state.confirm_deadline_ms ?? null
}

function buildWiredFormActions(props: WiredFormActionsProps): Component<WiredFormActionsProps> {
  const saveButton = baseButton({
    type: 'submit',
    variant: 'on-bright',
    disabled: !props.canSubmit,
    children: [props.busy ? 'Saving…' : 'Save wired settings'],
  })
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
        children: [nextProps.busy ? 'Saving…' : 'Save wired settings'],
      })
    },

    destroy(): void {
      saveButton.destroy()
    },
  }
}

/**
 * Builds the wired-sharing settings section. Takes no props — it is mounted
 * once by the Settings view and driven entirely by `wiredStore`.
 */
export function wiredPanel(): Component<void> {
  const headingId = nextElementId('wired-panel-heading')

  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'Serve addresses on one of this Sentry’s Ethernet ports, so a laptop plugged straight into it reaches the SDRs with no router in between.',
  ])

  // The form mounts its toggle row here — a line of its own beneath the title
  // and its description, rather than competing with the heading for the same
  // line.
  const headerControlsHost = el('div')

  const headerBlock = el('div', { class: 'flex flex-col gap-4' }, [
    introParagraph,
    headerControlsHost,
  ])

  // Both live regions stay mounted for the panel's whole lifetime and only
  // change text. Mounting a live region that already contains its message
  // frequently announces nothing at all.
  const busyStatusRegion = el('p', { attrs: { role: 'status' }, class: 'sr-only' }, [])
  const errorAlertRegion = el('p', { attrs: { role: 'alert' }, class: 'sr-only' }, [])

  const loadingParagraph = el('p', { class: 'm-0 text-[12px] text-signal-muted' }, [
    'Loading wired-sharing settings…',
  ])

  const statusPanelSlot = el('div')
  const countdownSlot = el('div')
  const blockedNotice = noticeBox({ tone: 'warn', role: 'alert', children: [] })
  const noCarrierNotice = noticeBox({
    tone: 'warn',
    role: 'status',
    children: [
      'Wired sharing is running, but nothing is plugged into that port. Connect a cable to the Sentry and to the machine that needs it — it should be given an address within a few seconds.',
    ],
  })
  const advertisedHostNotice = noticeBox({
    tone: 'warn',
    role: 'status',
    children: [
      'This Sentry publishes a fixed address to Sentinel (SENTRY_ADVERTISED_HOST), which is not the shared port’s address. A machine on the cable should use the address shown above instead.',
    ],
  })
  const errorNotice = noticeBox({ tone: 'danger', role: 'status', children: [] })
  const formSlot = el('div')
  const clientListSlot = el('div')
  // The form mounts its countdown slot and action row here — below the lease
  // list, which is not part of the form. `gap-6`, matching the panel's own
  // column, so the countdown notice and the action row read as two blocks.
  const actionsHost = el('div', { class: 'flex flex-col gap-6' })

  const contentBlock = el('div', { class: 'flex flex-col gap-6' }, [
    statusPanelSlot,
    blockedNotice.element,
    noCarrierNotice.element,
    advertisedHostNotice.element,
    errorNotice.element,
    formSlot,
    clientListSlot,
    actionsHost,
  ])

  const disclosure = disclosureSection({
    label: ['Wired (Ethernet) sharing'],
    headingLevel: 2,
    headingId,
    tone: 'panel',
    defaultOpen: false,
    persistKey: 'wired-panel',
    isBoxTitle: true,
    bodyClass: 'flex flex-col gap-6 pt-2',
    children: [headerBlock, busyStatusRegion, errorAlertRegion, loadingParagraph, contentBlock],
  })

  const panelRoot = el(
    'section',
    {
      class: 'flex flex-col bg-ground-panel p-card',
      attrs: { 'aria-labelledby': headingId },
    },
    [disclosure.element],
  )

  let statusPanel: Component<WiredStatusPanelProps> | null = null
  let confirmCountdown: Component<WiredConfirmCountdownProps> | null = null
  let form: Component<WiredFormProps> | null = null
  let clientList: Component<WiredClientListProps> | null = null

  function render(storeState: WiredStoreState): void {
    const isBusy = storeState.phase === 'submitting'
    const state = storeState.state

    setText(busyStatusRegion, isBusy ? 'Applying wired-sharing settings.' : '')
    setText(
      errorAlertRegion,
      storeState.phase === 'failed' && storeState.errorMessage ? storeState.errorMessage : '',
    )

    setVisible(loadingParagraph, state === null)
    setVisible(contentBlock, state !== null)

    if (state === null) return

    // Nothing to report while control is switched off: every readout in the
    // status panel is hidden in that state, leaving an empty block that still
    // took its height and its `gap-6`.
    setVisible(statusPanelSlot, state.control_enabled)
    if (!statusPanel) {
      statusPanel = wiredStatusPanel({ state })
      statusPanelSlot.appendChild(statusPanel.element)
    } else {
      statusPanel.update({ state })
    }

    const deadline = confirmDeadlineMs(state)
    setVisible(countdownSlot, deadline !== null)
    if (deadline !== null) {
      const countdownProps: WiredConfirmCountdownProps = {
        interfaceName: state.interface ?? null,
        deadlineMs: deadline,
        busy: isBusy,
        onConfirm: () => void confirmWired(),
        onDiscard: () => void disableWired(true),
        // The server rolls back on its own and tells nobody. Re-read the state
        // when the window closes, so the panel stops reporting a share that is
        // no longer running.
        onDeadlinePassed: () => void refresh(),
      }
      if (!confirmCountdown) {
        confirmCountdown = wiredConfirmCountdown(countdownProps)
        countdownSlot.appendChild(confirmCountdown.element)
      } else {
        confirmCountdown.update(countdownProps)
      }
    }

    const reason = blockedReason(state)
    setVisible(blockedNotice.element, reason !== null)
    if (reason !== null) {
      blockedNotice.update({ tone: 'warn', role: 'alert', children: [reason] })
    }

    // The single most useful thing this panel can say: sharing is up and
    // working, and the reason nothing has appeared is that the cable is not in.
    setVisible(noCarrierNotice.element, state.warnings.includes('no_carrier'))
    setVisible(
      advertisedHostNotice.element,
      state.warnings.includes('advertised_host_overrides_gateway'),
    )

    const showErrorNotice = storeState.phase === 'failed' && storeState.errorMessage !== null
    setVisible(errorNotice.element, showErrorNotice)
    if (showErrorNotice) {
      // The command's own output, when the server sent one. It is the only
      // thing that says *why* NetworkManager refused — printed verbatim rather
      // than summarised, because a paraphrase of an nmcli error is a guess.
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
      const formProps: WiredFormProps = {
        state,
        interfaces: storeState.interfaces,
        busy: isBusy,
        onSubmit: (config) => void save(config),
        // The switch acts now. `enable`/`disable` carry the acknowledgement
        // straight through, so the uplink check the operator ticked is the one
        // the server is told about.
        onEnabledChange: (enabled, confirmUplinkLoss) => {
          void (enabled ? enableWired(confirmUplinkLoss) : disableWired(confirmUplinkLoss))
        },
        actions: buildWiredFormActions,
        // The countdown belongs beside the button that caused it.
        beforeActions: [countdownSlot],
        headerControlsHost,
        actionsHost,
      }
      if (!form) {
        form = wiredForm(formProps)
        formSlot.appendChild(form.element)
      } else {
        form.update(formProps)
      }
    }

    const showClientList = state.configured
    setVisible(clientListSlot, showClientList)
    if (showClientList) {
      // `active`, not `configured`: the list is shown for a configured share
      // whether or not it is up, but a lease can only be released while it is —
      // dnsmasq is not there to accept the release otherwise.
      const clientListProps: WiredClientListProps = {
        clients: storeState.clients,
        sharingRunning: state.active,
      }
      if (!clientList) {
        clientList = wiredClientList(clientListProps)
        clientListSlot.appendChild(clientList.element)
      } else {
        clientList.update(clientListProps)
      }
    }
  }

  const unsubscribe = watchStore(wiredStore, render)

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
      form?.destroy()
      clientList?.destroy()
      blockedNotice.destroy()
      noCarrierNotice.destroy()
      advertisedHostNotice.destroy()
      errorNotice.destroy()
    },
  }
}
