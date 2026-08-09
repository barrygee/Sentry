import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../src/api/client.js'
import {
  consoleAuthStore,
  declineSetupPrompt,
  markUnauthenticated,
  mustSignIn,
  openSetupPrompt,
  refreshAuthState,
  setPassword,
  shouldWarnUnprotected,
  signIn,
} from '../../src/state/consoleAuth.js'

/**
 * Tests for which screen an operator is shown (ADR-0010).
 *
 * The security-shaped behaviour — what a session actually authorises — lives in
 * the backend suite, where it is enforced. What is asserted here is the part a
 * client gets to decide, and the part that would strand somebody if it were
 * wrong: never showing a sign-in screen with nothing to sign in to, and never
 * quietly dropping the "you have no password" warning.
 */

function serverSays(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    password_set: false,
    authenticated: true,
    updated_at: 0,
    minimum_password_length: 8,
    ...overrides,
  }
}

function resetStore(): void {
  consoleAuthStore.setState({
    passwordSet: false,
    authenticated: true,
    updatedAt: 0,
    minimumPasswordLength: 8,
    phase: 'loading',
    errorMessage: null,
    setupPromptOpen: false,
    setupDeclined: false,
  })
}

beforeEach(resetStore)
afterEach(() => {
  vi.restoreAllMocks()
})

describe('refreshAuthState', () => {
  it('opens the setup prompt on an unprotected controller', async () => {
    vi.spyOn(apiClient, 'authState').mockResolvedValue(serverSays())

    await refreshAuthState()

    expect(consoleAuthStore.state.setupPromptOpen).toBe(true)
  })

  it('does not reopen the prompt once declined this visit', async () => {
    vi.spyOn(apiClient, 'authState').mockResolvedValue(serverSays())
    await refreshAuthState()
    declineSetupPrompt()

    await refreshAuthState()

    // Otherwise every background refresh would reopen a dialog the operator
    // just dismissed — the console arguing with them rather than informing.
    expect(consoleAuthStore.state.setupPromptOpen).toBe(false)
  })

  it('never prompts when a password already exists', async () => {
    vi.spyOn(apiClient, 'authState').mockResolvedValue(
      serverSays({ password_set: true, authenticated: true }),
    )

    await refreshAuthState()

    expect(consoleAuthStore.state.setupPromptOpen).toBe(false)
  })

  it('leaves the console usable when the request fails', async () => {
    vi.spyOn(apiClient, 'authState').mockRejectedValue(new Error('network down'))

    await refreshAuthState()

    // A controller that cannot report its auth state is broken in a way the
    // device view surfaces far more usefully than a login screen would.
    expect(mustSignIn(consoleAuthStore.state)).toBe(false)
    expect(consoleAuthStore.state.phase).toBe('idle')
  })
})

describe('mustSignIn', () => {
  it('is false on an unprotected controller', () => {
    // The failure this guards: a sign-in screen with no password to enter,
    // which would lock an operator out of their own open console.
    expect(
      mustSignIn({ ...consoleAuthStore.state, passwordSet: false, authenticated: false }),
    ).toBe(false)
  })

  it('is true when a password exists and this browser has no session', () => {
    expect(mustSignIn({ ...consoleAuthStore.state, passwordSet: true, authenticated: false })).toBe(
      true,
    )
  })

  it('is false once signed in', () => {
    expect(mustSignIn({ ...consoleAuthStore.state, passwordSet: true, authenticated: true })).toBe(
      false,
    )
  })
})

describe('shouldWarnUnprotected', () => {
  it('stays hidden while the prompt is showing', () => {
    // Saying the same thing twice, once behind the other.
    expect(
      shouldWarnUnprotected({ ...consoleAuthStore.state, phase: 'idle', setupPromptOpen: true }),
    ).toBe(false)
  })

  it('appears once the prompt is declined', () => {
    expect(
      shouldWarnUnprotected({ ...consoleAuthStore.state, phase: 'idle', setupPromptOpen: false }),
    ).toBe(true)
  })

  it('stays hidden before the first answer arrives', () => {
    // Otherwise every page load would flash "no password" before the server
    // had been asked whether that is even true.
    expect(shouldWarnUnprotected({ ...consoleAuthStore.state, phase: 'loading' })).toBe(false)
  })

  it('stays hidden once a password exists', () => {
    expect(
      shouldWarnUnprotected({ ...consoleAuthStore.state, phase: 'idle', passwordSet: true }),
    ).toBe(false)
  })
})

describe('markUnauthenticated', () => {
  it('raises the sign-in screen when a password exists', () => {
    consoleAuthStore.setState({ passwordSet: true, authenticated: true })

    markUnauthenticated()

    expect(consoleAuthStore.state.authenticated).toBe(false)
  })

  it('is ignored on an unprotected controller', () => {
    // A 401 here would be a server bug, and showing a login screen with nothing
    // to log into would strand the operator rather than help them.
    consoleAuthStore.setState({ passwordSet: false, authenticated: true })

    markUnauthenticated()

    expect(consoleAuthStore.state.authenticated).toBe(true)
  })
})

describe('signIn', () => {
  it('reports the server’s message on a bad password', async () => {
    const { ApiError } = await import('../../src/api/client.js')
    vi.spyOn(apiClient, 'login').mockRejectedValue(
      new ApiError(
        401,
        { code: 'invalid_password', message: 'That password is not correct.' },
        'x',
      ),
    )

    const succeeded = await signIn('wrong')

    expect(succeeded).toBe(false)
    expect(consoleAuthStore.state.errorMessage).toBe('That password is not correct.')
    expect(consoleAuthStore.state.phase).toBe('failed')
  })

  it('re-reads state from the server on success', async () => {
    vi.spyOn(apiClient, 'login').mockResolvedValue(undefined)
    const authState = vi
      .spyOn(apiClient, 'authState')
      .mockResolvedValue(serverSays({ password_set: true, authenticated: true }))

    const succeeded = await signIn('a good long password')

    expect(succeeded).toBe(true)
    expect(authState).toHaveBeenCalled()
    expect(mustSignIn(consoleAuthStore.state)).toBe(false)
  })
})

describe('setPassword', () => {
  it('closes the prompt and clears the decline on success', async () => {
    vi.spyOn(apiClient, 'setConsolePassword').mockResolvedValue(undefined)
    vi.spyOn(apiClient, 'authState').mockResolvedValue(
      serverSays({ password_set: true, authenticated: true }),
    )
    declineSetupPrompt()

    await setPassword('a good long password', null)

    expect(consoleAuthStore.state.setupPromptOpen).toBe(false)
    expect(consoleAuthStore.state.setupDeclined).toBe(false)
  })

  it('keeps the prompt open and reports why on failure', async () => {
    const { ApiError } = await import('../../src/api/client.js')
    openSetupPrompt()
    vi.spyOn(apiClient, 'setConsolePassword').mockRejectedValue(
      new ApiError(422, { code: 'password_too_short', message: 'Too short.' }, 'x'),
    )

    const succeeded = await setPassword('abc', null)

    expect(succeeded).toBe(false)
    expect(consoleAuthStore.state.setupPromptOpen).toBe(true)
    expect(consoleAuthStore.state.errorMessage).toBe('Too short.')
  })
})
