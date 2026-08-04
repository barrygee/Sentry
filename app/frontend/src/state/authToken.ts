import { createStore, type Store } from '../core/observable.js'

/**
 * The operator-supplied `SENTRY_AUTH_TOKEN` (architecture §7.9), held in
 * `sessionStorage` so it survives a reload for the whole tab session.
 *
 * A module-level singleton because `api/client.ts` and the SSE stream are plain
 * modules — not components — and both need to read and react to the same token.
 */
const STORAGE_KEY = 'sentry.authToken'

export interface AuthTokenState {
  /** The operator-entered token, or `null` when auth is off (or not yet supplied). */
  token: string | null
  /** True once any request has come back `401`, so the token prompt should render. */
  promptRequired: boolean
}

function readStoredToken(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY)
  } catch {
    // sessionStorage unavailable (private browsing, disabled storage) — auth silently no-ops.
    return null
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token === null) {
      window.sessionStorage.removeItem(STORAGE_KEY)
    } else {
      window.sessionStorage.setItem(STORAGE_KEY, token)
    }
  } catch {
    // sessionStorage unavailable — the token simply won't survive a reload.
  }
}

export const authTokenStore: Store<AuthTokenState> = createStore<AuthTokenState>({
  token: readStoredToken(),
  promptRequired: false,
})

/** Stores `nextToken` (trimmed; empty clears it) and dismisses the prompt. */
export function setAuthToken(nextToken: string): void {
  const trimmed = nextToken.trim()
  const token = trimmed.length > 0 ? trimmed : null
  writeStoredToken(token)
  authTokenStore.setState({ token, promptRequired: false })
}

/** Marks that a request failed auth — called from `api/client.ts` on a `401`. */
export function requireAuthPrompt(): void {
  authTokenStore.setState({ promptRequired: true })
}

export function dismissAuthPrompt(): void {
  authTokenStore.setState({ promptRequired: false })
}

/** The current token, for callers that need it outside a subscription (fetch headers, SSE URL). */
export function currentAuthToken(): string | null {
  return authTokenStore.state.token
}
