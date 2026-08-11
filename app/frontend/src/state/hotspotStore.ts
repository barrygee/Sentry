import {
  apiClient,
  ApiError,
  type HotspotClient,
  type HotspotConfigRequest,
  type HotspotState,
  type WirelessInterface,
} from '../api/client.js'
import { liveAnnouncer } from '../core/liveAnnouncer.js'
import { createStore, type Store } from '../core/observable.js'

/**
 * The hotspot's client-side model.
 *
 * A store of its own rather than fields on `sdrsStore.ts`: that one is the
 * SSE-driven device model, and the hotspot is request/response state about the
 * host's network. Keeping them apart means neither has to know the other exists,
 * and both stay trivially testable with plain fixture objects.
 *
 * **The passphrase is never held here.** It lives in the form's local state for
 * exactly as long as it takes to send, and is never written to this store,
 * `sessionStorage` or a URL. Nothing about the console's own credential is held
 * in this browser either — that is an HttpOnly cookie (ADR-0010) this code
 * cannot read. The hotspot key is the higher-value secret and it has no
 * reason to outlive the request.
 */

/** What the dialog is currently doing. Drives which controls are live. */
export type HotspotPhase =
  'loading' | 'form' | 'submitting' | 'awaiting-confirm' | 'succeeded' | 'failed'

export interface HotspotStoreState {
  state: HotspotState | null
  interfaces: WirelessInterface[]
  /** `null` means the host could not be asked — never render it as "no clients". */
  clients: HotspotClient[] | null
  phase: HotspotPhase
  /** The last operator-facing failure message, or null. Never contains a secret. */
  errorMessage: string | null
  errorCode: string | null
}

/**
 * Turn a server error code into a sentence an operator can act on.
 *
 * Follows `sdrsStore.ts`'s `humanize*ErrorCode` idiom: a raw code is never rendered.
 * Falls back to the server's own message, which is already written for a human
 * and already redacted of any passphrase.
 */
export function humanizeHotspotError(code: string, fallback: string): string {
  switch (code) {
    case 'hotspot_control_disabled':
      return 'Hotspot control is switched off on this Sentry. Turn it on in the hotspot settings.'
    case 'auth_token_required':
      return 'Set a Sentry controller password before starting a hotspot — otherwise anyone who joins the network can reach this controller without credentials.'
    case 'hotspot_unavailable':
      return 'This Sentry cannot manage a WiFi hotspot: NetworkManager was not reachable.'
    case 'passphrase_required':
      return 'Enter a password for the hotspot.'
    case 'hotspot_not_configured':
      return 'Set the network name and password first.'
    case 'uplink_loss_unconfirmed':
      return 'That interface is carrying this Sentry’s own network connection. Confirm before continuing.'
    case 'no_wireless_interface':
      return 'This Sentry has no wireless interface that can host a network.'
    case 'interface_not_found':
      return 'That wireless interface is no longer present.'
    case 'interface_ap_unsupported':
      return 'That wireless interface cannot host a network.'
    case 'hotspot_busy':
      return 'Another hotspot change is still running. Wait a moment and try again.'
    case 'no_pending_confirmation':
      return 'There is no hotspot change waiting to be confirmed — it may have already rolled back.'
    case 'hotspot_command_timeout':
      return 'The network command did not finish in time — the radio or NetworkManager may be stuck. Its output is in the Sentry log: run `docker compose logs sentry` on the Pi.'
    case 'hotspot_command_failed':
      return 'The network command failed. Its output is in the Sentry log: run `docker compose logs sentry` on the Pi.'
    default:
      return fallback
  }
}

function describeError(error: unknown, fallback: string): { code: string; message: string } {
  if (error instanceof ApiError) {
    const code = error.detail?.code ?? 'hotspot_request_failed'
    return { code, message: humanizeHotspotError(code, error.message || fallback) }
  }
  return { code: 'hotspot_request_failed', message: fallback }
}

/** The hotspot's client-side model — request/response state about the host's WiFi network. */
export const hotspotStore: Store<HotspotStoreState> = createStore<HotspotStoreState>({
  state: null,
  interfaces: [],
  clients: null,
  phase: 'loading',
  errorMessage: null,
  errorCode: null,
})

/** Whether a hotspot change is currently on trial and will revert if unconfirmed. */
export function isAwaitingConfirmation(state: Readonly<HotspotStoreState>): boolean {
  return state.state?.pending_confirmation === true
}

/** Whether the chosen interface is also this Sentry's own way onto the network. */
export function wouldDropUplink(state: Readonly<HotspotStoreState>): boolean {
  return state.state?.uplink_interface_is_hotspot_interface === true
}

/** The address a joined client should point Sentinel at. */
export function gatewayAddress(state: Readonly<HotspotStoreState>): string | null {
  return state.state?.gateway_address ?? null
}

/** Whether any mutating control should be enabled at all. */
export function canMutate(state: Readonly<HotspotStoreState>): boolean {
  return (
    state.state !== null &&
    state.state.available &&
    state.state.control_enabled &&
    state.state.auth_token_configured
  )
}

/**
 * Clear leftover error state when the settings screen is left.
 *
 * Was `closeDialog`. The dialog is gone, but the reset it performed is not
 * incidental: a failure message left standing would greet the operator again
 * the next time they open Settings, describing an attempt they made minutes ago
 * and have very likely forgotten.
 */
export function resetTransientState(): void {
  hotspotStore.setState({ errorMessage: null, errorCode: null })
}

/** Apply a fresh state payload, deriving the phase from what the server reports. */
export function applyState(nextState: HotspotState): void {
  hotspotStore.setState({
    state: nextState,
    phase: nextState.pending_confirmation ? 'awaiting-confirm' : 'form',
  })
}

/** Records an error onto the store, deriving its operator-facing message from `error`. */
export function recordError(error: unknown, fallback: string): void {
  const described = describeError(error, fallback)
  hotspotStore.setState({
    errorCode: described.code,
    errorMessage: described.message,
    phase: 'failed',
  })
}

/** Reloads the hotspot's settings, available interfaces and connected-client list. */
export async function refresh(): Promise<void> {
  try {
    const [nextState, interfacesResponse] = await Promise.all([
      apiClient.getHotspot(),
      apiClient.getHotspotInterfaces(),
    ])
    hotspotStore.setState({ interfaces: [...interfacesResponse.interfaces] })
    applyState(nextState)
    hotspotStore.setState({ errorMessage: null, errorCode: null })
  } catch (error) {
    recordError(error, 'Could not read the hotspot settings.')
  }
  await refreshClients()
}

/**
 * Switch this Sentry's hotspot control on or off (ADR-0013).
 *
 * Refreshes afterwards rather than assuming: turning control on changes which
 * controller answers every other hotspot route, so what the host actually
 * reports back is the only trustworthy picture of the new state.
 */
export async function setControlEnabled(enabled: boolean): Promise<boolean> {
  try {
    await apiClient.setHotspotControl(enabled)
  } catch (error) {
    recordError(error, 'Could not change hotspot control.')
    return false
  }
  await refresh()
  return true
}

/** Reloads only the connected-client list, without disturbing the settings form. */
export async function refreshClients(): Promise<void> {
  try {
    const response = await apiClient.getHotspotClients()
    // Preserve the null: "cannot tell" and "nobody connected" are different
    // answers and the UI renders them differently. An absent key is also
    // "cannot tell", so `?? null` collapses only that, never an empty list.
    hotspotStore.setState({ clients: response.clients == null ? null : [...response.clients] })
  } catch {
    // A failed client list must never blank out the settings form — it is
    // supplementary information, not the point of the panel.
    hotspotStore.setState({ clients: null })
  }
}

/**
 * Save the configuration.
 *
 * `passphrase` is omitted from the body entirely when unchanged rather than
 * sent as null — that omission *is* the "keep the stored password" signal
 * the server contract defines.
 */
export async function save(config: HotspotConfigRequest): Promise<boolean> {
  hotspotStore.setState({ phase: 'submitting', errorMessage: null, errorCode: null })
  try {
    applyState(await apiClient.putHotspot(config))
    liveAnnouncer().announcePolite(
      config.enabled ? 'Hotspot settings saved and started.' : 'Hotspot settings saved.',
    )
    void refreshClients()
    return true
  } catch (error) {
    recordError(error, 'Could not save the hotspot settings.')
    return false
  }
}

/** Shared submit-announce-or-record path for the three activation routes. */
async function runActivation(
  call: () => Promise<HotspotState>,
  successAnnouncement: string,
  failureFallback: string,
): Promise<boolean> {
  hotspotStore.setState({ phase: 'submitting', errorMessage: null, errorCode: null })
  try {
    applyState(await call())
    liveAnnouncer().announcePolite(successAnnouncement)
    void refreshClients()
    return true
  } catch (error) {
    recordError(error, failureFallback)
    return false
  }
}

/** Starts the hotspot, optionally confirming that this may drop the host's own uplink. */
export async function enable(confirmUplinkLoss: boolean): Promise<boolean> {
  return runActivation(
    () => apiClient.enableHotspot({ confirm_uplink_loss: confirmUplinkLoss }),
    'Hotspot started.',
    'Could not start the hotspot.',
  )
}

/** Stops the hotspot, optionally confirming that this may drop the host's own uplink. */
export async function disable(confirmUplinkLoss: boolean): Promise<boolean> {
  return runActivation(
    () => apiClient.disableHotspot({ confirm_uplink_loss: confirmUplinkLoss }),
    'Hotspot stopped.',
    'Could not stop the hotspot.',
  )
}

/** Confirms an on-trial hotspot change so it persists rather than rolling back. */
export async function confirm(): Promise<boolean> {
  return runActivation(
    () => apiClient.confirmHotspot(),
    'Hotspot confirmed. It will now start automatically.',
    'Could not confirm the hotspot.',
  )
}

/** Deletes the hotspot configuration entirely. */
export async function forget(): Promise<boolean> {
  hotspotStore.setState({ phase: 'submitting' })
  try {
    await apiClient.deleteHotspot()
    liveAnnouncer().announcePolite('Hotspot configuration deleted.')
    await refresh()
    return true
  } catch (error) {
    recordError(error, 'Could not delete the hotspot configuration.')
    return false
  }
}

/**
 * React to a rollback that happened on the server without us asking.
 *
 * Called by the SDRs stream when a `hotspot_rollback` notice arrives, so an
 * operator who closed the dialog still learns their hotspot reverted —
 * assertively, because it means the network they were about to rely on is
 * gone.
 */
export function handleRollbackNotice(message: string): void {
  liveAnnouncer().announceAssertive(message)
  void refresh()
}
