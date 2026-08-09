import { apiClient, ApiError } from '../api/client.js'
import { createStore, type Store } from '../core/observable.js'

/**
 * The console's authentication state (ADR-0010).
 *
 * Replaces `authToken.ts`. Nothing is stored in the browser any more — the
 * session is an `HttpOnly` cookie, which by design this code cannot read. What
 * lives here is only what the UI needs to decide *which screen to show*:
 * whether a password exists, and whether this browser is signed in.
 *
 * **The password itself is never held here.** It exists in a form field for as
 * long as it takes to send, exactly as the hotspot passphrase does.
 */

/** What the UI is currently doing about authentication. */
export type ConsoleAuthPhase = 'loading' | 'idle' | 'submitting' | 'failed'

export interface ConsoleAuthState {
  /** Whether this console has a password at all. `false` means it is open to anyone. */
  passwordSet: boolean
  /** Whether this browser may use the management API — always true on an open console. */
  authenticated: boolean
  /** Unix ms the password last changed; 0 when never. */
  updatedAt: number
  /** Shortest password the API will accept, so the UI need not hardcode it. */
  minimumPasswordLength: number
  phase: ConsoleAuthPhase
  /** Operator-facing failure text, or null. Never contains a password. */
  errorMessage: string | null
  /**
   * Whether the "set a password" prompt is showing.
   *
   * Raised automatically once per visit while no password exists, and again
   * whenever the operator asks for it from the warning that replaces it. The
   * operator can decline; they are asked again next visit, because an open
   * console is a standing condition rather than a one-off notice.
   */
  setupPromptOpen: boolean
  /** True once the prompt has been declined this visit, which reveals the warning. */
  setupDeclined: boolean
}

export const consoleAuthStore: Store<ConsoleAuthState> = createStore<ConsoleAuthState>({
  passwordSet: false,
  // Assumed true until proven otherwise, so a console that turns out to be open
  // never flashes a login screen it would immediately have to take away.
  authenticated: true,
  updatedAt: 0,
  minimumPasswordLength: 8,
  phase: 'loading',
  errorMessage: null,
  setupPromptOpen: false,
  setupDeclined: false,
})

/** Whether the sign-in screen should replace the whole app. */
export function mustSignIn(state: Readonly<ConsoleAuthState>): boolean {
  return state.passwordSet && !state.authenticated
}

/** Whether the "no password set" warning should be visible. */
export function shouldWarnUnprotected(state: Readonly<ConsoleAuthState>): boolean {
  return state.phase !== 'loading' && !state.passwordSet && !state.setupPromptOpen
}

/**
 * Read the current authentication state from the server.
 *
 * Called once at startup and after every change. The server is the only
 * authority here — the session cookie is `HttpOnly`, so this code genuinely
 * cannot tell whether it holds a valid one without asking.
 */
export async function refreshAuthState(): Promise<void> {
  try {
    const state = await apiClient.authState()
    consoleAuthStore.setState({
      passwordSet: state.password_set,
      authenticated: state.authenticated,
      updatedAt: state.updated_at,
      minimumPasswordLength: state.minimum_password_length,
      phase: 'idle',
      // Ask for a password on arrival at an unprotected console, unless this
      // visit has already been asked and declined.
      setupPromptOpen: !state.password_set && !consoleAuthStore.state.setupDeclined,
    })
  } catch {
    // A console that cannot report its auth state is broken in a way the device
    // view will surface far more usefully than a login screen would.
    consoleAuthStore.setState({ phase: 'idle' })
  }
}

/** Exchange the password for a session. */
export async function signIn(password: string): Promise<boolean> {
  consoleAuthStore.setState({ phase: 'submitting', errorMessage: null })
  try {
    await apiClient.login(password)
  } catch (error) {
    consoleAuthStore.setState({
      phase: 'failed',
      errorMessage: messageFor(error, 'That password is not correct.'),
    })
    return false
  }
  await refreshAuthState()
  return true
}

/** Discard this browser's session and return to the sign-in screen. */
export async function signOut(): Promise<void> {
  try {
    await apiClient.logout()
  } finally {
    // Refreshed either way: if the request failed the cookie may still be gone,
    // and the server's answer is the only one that counts.
    await refreshAuthState()
  }
}

/**
 * Set the first password, or change an existing one.
 *
 * `currentPassword` is required by the server whenever one is already set.
 */
export async function setPassword(
  newPassword: string,
  currentPassword: string | null,
): Promise<boolean> {
  consoleAuthStore.setState({ phase: 'submitting', errorMessage: null })
  try {
    await apiClient.setConsolePassword(newPassword, currentPassword)
  } catch (error) {
    consoleAuthStore.setState({
      phase: 'failed',
      errorMessage: messageFor(error, 'That password could not be set.'),
    })
    return false
  }
  consoleAuthStore.setState({ setupPromptOpen: false, setupDeclined: false })
  await refreshAuthState()
  return true
}

/** Open the "set a password" prompt, from the warning or from Settings. */
export function openSetupPrompt(): void {
  consoleAuthStore.setState({ setupPromptOpen: true, errorMessage: null, phase: 'idle' })
}

/** Decline the prompt for this visit. The warning takes its place. */
export function declineSetupPrompt(): void {
  consoleAuthStore.setState({ setupPromptOpen: false, setupDeclined: true, errorMessage: null })
}

/** Note that a request came back 401, so the sign-in screen should appear. */
export function markUnauthenticated(): void {
  // Only meaningful once a password exists; on an open console a 401 would be a
  // server bug, and showing a login screen with nothing to log into would strand
  // the operator rather than help them.
  if (consoleAuthStore.state.passwordSet) {
    consoleAuthStore.setState({ authenticated: false })
  }
}

/** The server's own message when it sent one, else `fallback`. Never a password. */
function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.detail?.message) {
    return error.detail.message
  }
  return fallback
}
