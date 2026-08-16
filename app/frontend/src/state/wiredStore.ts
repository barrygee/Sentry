import {
  apiClient,
  ApiError,
  type WiredClient,
  type WiredInterface,
  type WiredShareConfigRequest,
  type WiredShareState,
} from '../api/client.js'
import { liveAnnouncer } from '../core/liveAnnouncer.js'
import { createStore, type Store } from '../core/observable.js'

/**
 * Wired sharing's client-side model (ADR-0014).
 *
 * A store of its own rather than fields on `hotspotStore`: the two features
 * drive different interfaces through different endpoints and can be in
 * completely different states at once — sharing up while the hotspot is off is
 * the expected arrangement on a one-radio Pi, not an edge case. Keeping them
 * apart means neither has to know the other exists.
 *
 * There is no secret anywhere in here, and unlike the hotspot's store that is
 * not a discipline being maintained — a wired share simply has no passphrase.
 * The cable is the credential.
 */

/** What the panel is currently doing. Drives which controls are live. */
export type WiredPhase =
  'loading' | 'form' | 'submitting' | 'awaiting-confirm' | 'succeeded' | 'failed'

export interface WiredStoreState {
  state: WiredShareState | null
  interfaces: WiredInterface[]
  /** `null` means the host could not be asked — never render it as "no clients". */
  clients: WiredClient[] | null
  phase: WiredPhase
  /** The last operator-facing failure message, or null. */
  errorMessage: string | null
  errorCode: string | null
  /**
   * The failed command's own output, when the server sent one.
   *
   * Taken from the *error response*, not from `state.last_error`. On a failure
   * the store keeps the pre-request state, whose `last_error` is whatever it
   * was before — usually `null` — so reading it there would show nothing at the
   * one moment it mattered. The same trap the hotspot store fell into, avoided
   * here from the start.
   */
  errorCommandOutput: string | null
}

/**
 * Turn a server error code into a sentence an operator can act on.
 *
 * Follows the `humanize*ErrorCode` idiom the other stores use: a raw code is
 * never rendered. Falls back to the server's own message, which is already
 * written for a human.
 */
export function humanizeWiredError(code: string, fallback: string): string {
  switch (code) {
    case 'wired_control_disabled':
      return 'Host network control is switched off on this Sentry. Turn it on in the hotspot settings — the same switch covers the Ethernet port.'
    case 'console_password_required':
      return 'Set a Sentry controller password before sharing an Ethernet port — otherwise anyone who plugs in a cable can reach this controller without credentials.'
    case 'wired_unavailable':
      return 'This Sentry cannot share an Ethernet port: NetworkManager was not reachable.'
    case 'wired_not_configured':
      return 'Choose which Ethernet port to share and save it first.'
    case 'uplink_loss_unconfirmed':
      return 'That port is carrying this Sentry’s own network connection. Confirm before continuing.'
    case 'no_wired_interface':
      return 'This Sentry has no Ethernet port that could be shared.'
    case 'interface_not_found':
      return 'That Ethernet port is no longer present.'
    case 'wired_busy':
      return 'Another wired-sharing change is still running. Wait a moment and try again.'
    case 'wired_not_running':
      return 'Wired sharing is not running, so it has no leases to release.'
    case 'no_pending_confirmation':
      return 'There is no wired-sharing change waiting to be confirmed — it may have already rolled back.'
    case 'wired_command_timeout':
      return 'The network command did not finish in time — NetworkManager may be stuck. Its output is in the Sentry log: run `docker compose logs sentry` on the Pi.'
    case 'wired_command_failed':
      return 'The network command failed. Its output is in the Sentry log: run `docker compose logs sentry` on the Pi.'
    default:
      return fallback
  }
}

function describeError(
  error: unknown,
  fallback: string,
): { code: string; message: string; commandOutput: string | null } {
  if (error instanceof ApiError) {
    const code = error.detail?.code ?? 'wired_request_failed'
    // `_as_http_exception` spreads the service error's context into the detail,
    // and `stderr_tail` rides along in it.
    const stderrTail = error.detail?.['stderr_tail']
    return {
      code,
      message: humanizeWiredError(code, error.message || fallback),
      commandOutput: typeof stderrTail === 'string' && stderrTail !== '' ? stderrTail : null,
    }
  }
  return { code: 'wired_request_failed', message: fallback, commandOutput: null }
}

/** Wired sharing's client-side model. */
export const wiredStore: Store<WiredStoreState> = createStore<WiredStoreState>({
  state: null,
  interfaces: [],
  clients: null,
  phase: 'loading',
  errorMessage: null,
  errorCode: null,
  errorCommandOutput: null,
})

/** Whether a change is currently on trial and will revert if unconfirmed. */
export function isAwaitingConfirmation(state: Readonly<WiredStoreState>): boolean {
  return state.state?.pending_confirmation === true
}

/** Whether the chosen port is also this Sentry's own way onto the network. */
export function wouldDropUplink(state: Readonly<WiredStoreState>): boolean {
  return state.state?.uplink_interface_is_share_interface === true
}

/** The address a cabled machine should point Sentinel at. */
export function gatewayAddress(state: Readonly<WiredStoreState>): string | null {
  return state.state?.gateway_address ?? null
}

/** Whether any mutating control should be enabled at all. */
export function canMutate(state: Readonly<WiredStoreState>): boolean {
  return (
    state.state !== null &&
    state.state.available &&
    state.state.control_enabled &&
    state.state.console_password_set
  )
}

/**
 * Clear leftover error state when the settings screen is left.
 *
 * A failure message left standing would greet the operator again the next time
 * they open Settings, describing an attempt they made minutes ago and have very
 * likely forgotten.
 */
export function resetTransientState(): void {
  wiredStore.setState({ errorMessage: null, errorCode: null, errorCommandOutput: null })
}

/** Apply a fresh state payload, deriving the phase from what the server reports. */
export function applyState(nextState: WiredShareState): void {
  wiredStore.setState({
    state: nextState,
    phase: nextState.pending_confirmation ? 'awaiting-confirm' : 'form',
  })
}

/** Records an error onto the store, deriving its operator-facing message from `error`. */
export function recordError(error: unknown, fallback: string): void {
  const described = describeError(error, fallback)
  wiredStore.setState({
    errorCode: described.code,
    errorMessage: described.message,
    errorCommandOutput: described.commandOutput,
    phase: 'failed',
  })
}

/** Reloads the share's settings, available ports and lease list. */
export async function refresh(): Promise<void> {
  try {
    const [nextState, interfacesResponse] = await Promise.all([
      apiClient.getWired(),
      apiClient.getWiredInterfaces(),
    ])
    wiredStore.setState({ interfaces: [...interfacesResponse.interfaces] })
    applyState(nextState)
    wiredStore.setState({ errorMessage: null, errorCode: null, errorCommandOutput: null })
  } catch (error) {
    recordError(error, 'Could not read the wired-sharing settings.')
  }
  await refreshClients()
}

/**
 * Ask the share to forget one machine's DHCP lease.
 *
 * Refreshes the list rather than removing the row locally: the server decides
 * whether the release actually took, and a row that vanished optimistically
 * would claim more than the response does.
 */
export async function releaseLease(macAddress: string): Promise<boolean> {
  try {
    await apiClient.releaseWiredLease(macAddress)
  } catch (error) {
    recordError(error, 'Could not release that lease.')
    return false
  }
  liveAnnouncer().announcePolite('Lease released.')
  await refreshClients()
  return true
}

/** Reloads only the lease list, without disturbing the settings form. */
export async function refreshClients(): Promise<void> {
  try {
    const response = await apiClient.getWiredClients()
    // Preserve the null: "cannot tell" and "nothing plugged in" are different
    // answers and the UI renders them differently. An absent key is also
    // "cannot tell", so `?? null` collapses only that, never an empty list.
    wiredStore.setState({ clients: response.clients == null ? null : [...response.clients] })
  } catch {
    // A failed lease list must never blank out the settings form — it is
    // supplementary information, not the point of the panel.
    wiredStore.setState({ clients: null })
  }
}

/** Save the configuration. */
export async function save(config: WiredShareConfigRequest): Promise<boolean> {
  wiredStore.setState({
    phase: 'submitting',
    errorMessage: null,
    errorCode: null,
    errorCommandOutput: null,
  })
  try {
    applyState(await apiClient.putWired(config))
    liveAnnouncer().announcePolite(
      config.enabled ? 'Wired sharing saved and started.' : 'Wired sharing settings saved.',
    )
    void refreshClients()
    return true
  } catch (error) {
    recordError(error, 'Could not save the wired-sharing settings.')
    return false
  }
}

/** Shared submit-announce-or-record path for the three activation routes. */
async function runActivation(
  call: () => Promise<WiredShareState>,
  successAnnouncement: string,
  failureFallback: string,
): Promise<boolean> {
  wiredStore.setState({
    phase: 'submitting',
    errorMessage: null,
    errorCode: null,
    errorCommandOutput: null,
  })
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

/** Starts sharing, optionally confirming that this may drop the host's own uplink. */
export async function enable(confirmUplinkLoss: boolean): Promise<boolean> {
  return runActivation(
    () => apiClient.enableWired({ confirm_uplink_loss: confirmUplinkLoss }),
    'Wired sharing started.',
    'Could not start wired sharing.',
  )
}

/** Stops sharing, optionally confirming that this may drop the host's own uplink. */
export async function disable(confirmUplinkLoss: boolean): Promise<boolean> {
  return runActivation(
    () => apiClient.disableWired({ confirm_uplink_loss: confirmUplinkLoss }),
    'Wired sharing stopped.',
    'Could not stop wired sharing.',
  )
}

/** Confirms an on-trial change so it persists rather than rolling back. */
export async function confirm(): Promise<boolean> {
  return runActivation(
    () => apiClient.confirmWired(),
    'Wired sharing confirmed. It will now start automatically.',
    'Could not confirm wired sharing.',
  )
}

/** Deletes the wired-sharing configuration entirely. */
export async function forget(): Promise<boolean> {
  wiredStore.setState({ phase: 'submitting' })
  try {
    await apiClient.deleteWired()
    liveAnnouncer().announcePolite('Wired-sharing configuration deleted.')
    await refresh()
    return true
  } catch (error) {
    recordError(error, 'Could not delete the wired-sharing configuration.')
    return false
  }
}

/**
 * React to a rollback that happened on the server without us asking.
 *
 * Called by the SDRs stream when a `wired_rollback` notice arrives, so an
 * operator who navigated away still learns their share reverted — assertively,
 * because it means the network they were about to rely on is gone.
 */
export function handleRollbackNotice(message: string): void {
  liveAnnouncer().announceAssertive(message)
  void refresh()
}
