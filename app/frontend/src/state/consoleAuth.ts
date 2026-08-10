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
})

/** Whether the sign-in screen should replace the whole app. */
export function mustSignIn(state: Readonly<ConsoleAuthState>): boolean {
  return state.passwordSet && !state.authenticated
}

/**
 * Whether the "no password set" warning should be visible.
 *
 * It has no dismissal any more. An open console is a standing condition, not a
 * notice to acknowledge, and the warning is now the only thing that says so —
 * the dialog that used to raise itself on arrival has gone.
 */
export function shouldWarnUnprotected(state: Readonly<ConsoleAuthState>): boolean {
  return state.phase !== 'loading' && !state.passwordSet
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
  await refreshAuthState()
  return true
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
