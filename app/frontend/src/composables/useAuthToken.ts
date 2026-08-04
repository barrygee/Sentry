import { ref, type Ref } from 'vue'

const STORAGE_KEY = 'sentry.authToken'

export interface AuthTokenHandle {
  /** The operator-entered token, or `null` when `SENTRY_AUTH_TOKEN` auth is off (or not yet supplied). */
  token: Ref<string | null>
  /** True once any request has come back `401`, so `AuthTokenPrompt` should render. */
  promptRequired: Ref<boolean>
  /** Store `nextToken` (trimmed; empty clears it) and dismiss the prompt. */
  setToken: (nextToken: string) => void
  /** Mark that a request failed auth — called from `api/client.ts` on a `401`. */
  requirePrompt: () => void
  dismissPrompt: () => void
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

let sharedHandle: AuthTokenHandle | null = null

/**
 * The operator-supplied `SENTRY_AUTH_TOKEN` (architecture §7.9), held in
 * `sessionStorage` rather than a component ref so it survives the whole tab
 * session. A module-level singleton, like `useLiveAnnouncer`, because
 * `api/client.ts` and `useSdrsStream` are plain modules/composables (not
 * components) that both need to read and react to the same token.
 */
export function useAuthToken(): AuthTokenHandle {
  sharedHandle ??= createAuthTokenHandle()
  return sharedHandle
}

/** Test-only escape hatch so each test file starts from a clean token store. */
export function resetAuthTokenForTesting(): void {
  sharedHandle = null
}

function createAuthTokenHandle(): AuthTokenHandle {
  const token = ref<string | null>(readStoredToken())
  const promptRequired = ref(false)

  function setToken(nextToken: string): void {
    const trimmed = nextToken.trim()
    token.value = trimmed.length > 0 ? trimmed : null
    writeStoredToken(token.value)
    promptRequired.value = false
  }

  function requirePrompt(): void {
    promptRequired.value = true
  }

  function dismissPrompt(): void {
    promptRequired.value = false
  }

  return { token, promptRequired, setToken, requirePrompt, dismissPrompt }
}
