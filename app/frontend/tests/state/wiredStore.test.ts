import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient, ApiError, type WiredShareState } from '../../src/api/client.js'
import {
  applyState,
  canMutate,
  confirm,
  disable,
  enable,
  forget,
  gatewayAddress,
  handleRollbackNotice,
  humanizeWiredError,
  isAwaitingConfirmation,
  recordError,
  refresh,
  refreshClients,
  releaseLease,
  resetTransientState,
  save,
  wiredStore,
  wouldDropUplink,
} from '../../src/state/wiredStore.js'

/**
 * Tests for the wired-sharing store.
 *
 * Three contracts here are load-bearing rather than incidental, and each has a
 * matching test because each has a failure mode that looks like working code:
 *
 * 1. **`null` clients survive.** "This host cannot tell you" and "nothing is
 *    plugged in" are different answers. A `?? []` anywhere in the lease path
 *    would render an empty network on a Pi whose lease file is simply
 *    unreadable.
 * 2. **A failed lease read never blanks the form.** The list is supplementary;
 *    losing it must not take the settings down with it.
 * 3. **The failing command's output comes off the error response**, not off
 *    `state.last_error` — which on a failure still holds the pre-request value.
 *    That is the trap the hotspot store fell into, and the reason this one was
 *    written the other way round from the start.
 */

function state(overrides: Partial<WiredShareState> = {}): WiredShareState {
  return {
    available: true,
    control_enabled: true,
    console_password_set: true,
    configured: true,
    enabled: false,
    active: false,
    pending_confirmation: false,
    carrier_up: true,
    uplink_interface_is_share_interface: false,
    warnings: [],
    generated_at: 0,
    ...overrides,
  } as WiredShareState
}

function apiError(detail: Record<string, unknown> | null, status = 500): ApiError {
  return new ApiError(status, detail as never, 'fallback message')
}

const EMPTY = {
  state: null,
  interfaces: [],
  clients: null,
  phase: 'loading' as const,
  errorMessage: null,
  errorCode: null,
  errorCommandOutput: null,
}

// Mounted once, not per test. `liveAnnouncer()` is a module-level singleton
// that binds to these nodes on first use and holds those references for the
// rest of the file — so replacing the body between tests would leave it writing
// into detached elements, and every announcement assertion would read empty.
beforeAll(() => {
  document.body.innerHTML = `
    <div id="live-region-polite"></div>
    <div id="live-region-assertive"></div>
  `
})

beforeEach(() => {
  const assertiveRegion = document.getElementById('live-region-assertive')
  if (assertiveRegion) assertiveRegion.textContent = ''
  wiredStore.setState(EMPTY)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('humanizeWiredError', () => {
  it.each([
    ['wired_control_disabled', 'hotspot settings'],
    ['console_password_required', 'controller password'],
    ['wired_unavailable', 'NetworkManager'],
    ['wired_not_configured', 'Ethernet port'],
    ['uplink_loss_unconfirmed', 'own network connection'],
    ['no_wired_interface', 'no Ethernet port'],
    ['interface_not_found', 'no longer present'],
    ['wired_busy', 'still running'],
    ['wired_not_running', 'not running'],
    ['no_pending_confirmation', 'already rolled back'],
    ['wired_command_timeout', 'did not finish in time'],
    ['wired_command_failed', 'network command failed'],
  ])('turns %s into a sentence an operator can act on', (code, expected) => {
    // A raw code is never rendered — the same idiom the other stores follow.
    expect(humanizeWiredError(code, 'fallback')).toContain(expected)
  })

  it('falls back to the server’s own message for a code it does not know', () => {
    // The server writes for a human too, so an unknown code degrades to that
    // rather than to a machine token.
    expect(humanizeWiredError('something_new', 'the server said this')).toBe('the server said this')
  })
})

describe('recordError', () => {
  it('takes the command output from the error response, not the stale state', () => {
    recordError(
      apiError({ code: 'wired_command_failed', stderr_tail: 'Error: no such device' }),
      'fallback',
    )

    expect(wiredStore.state.errorCode).toBe('wired_command_failed')
    expect(wiredStore.state.errorCommandOutput).toBe('Error: no such device')
    expect(wiredStore.state.phase).toBe('failed')
  })

  it('treats an empty stderr_tail as no output rather than an empty block', () => {
    recordError(apiError({ code: 'wired_command_failed', stderr_tail: '' }), 'fallback')

    expect(wiredStore.state.errorCommandOutput).toBeNull()
  })

  it('ignores a non-string stderr_tail rather than rendering it', () => {
    recordError(apiError({ code: 'wired_command_failed', stderr_tail: 42 }), 'fallback')

    expect(wiredStore.state.errorCommandOutput).toBeNull()
  })

  it('uses a generic code when the failure is not an ApiError at all', () => {
    // A network-level failure has no envelope to read a code from.
    recordError(new TypeError('Failed to fetch'), 'Could not reach this Sentry.')

    expect(wiredStore.state.errorCode).toBe('wired_request_failed')
    expect(wiredStore.state.errorMessage).toBe('Could not reach this Sentry.')
  })

  it('uses a generic code when the envelope carries no code', () => {
    recordError(apiError(null), 'fallback')

    expect(wiredStore.state.errorCode).toBe('wired_request_failed')
  })

  it('falls back to the caller’s message when the envelope carries an empty one', () => {
    // `ApiError.message` is the detail's `message` when present; an empty one
    // would otherwise render as a blank notice with no explanation at all.
    recordError(
      apiError({ code: 'something_new', message: '' }),
      'Could not save the wired-sharing settings.',
    )

    expect(wiredStore.state.errorMessage).toBe('Could not save the wired-sharing settings.')
  })
})

describe('derived reads', () => {
  it('reports nothing on trial before any state has arrived', () => {
    expect(isAwaitingConfirmation(wiredStore.state)).toBe(false)
    expect(wouldDropUplink(wiredStore.state)).toBe(false)
    expect(gatewayAddress(wiredStore.state)).toBeNull()
    expect(canMutate(wiredStore.state)).toBe(false)
  })

  it('reports a change on trial', () => {
    applyState(state({ pending_confirmation: true }))

    expect(isAwaitingConfirmation(wiredStore.state)).toBe(true)
    expect(wiredStore.state.phase).toBe('awaiting-confirm')
  })

  it('derives the plain form phase when nothing is on trial', () => {
    applyState(state({ pending_confirmation: false }))

    expect(wiredStore.state.phase).toBe('form')
  })

  it('reports when the chosen port is also this Sentry’s own link', () => {
    applyState(state({ uplink_interface_is_share_interface: true }))

    expect(wouldDropUplink(wiredStore.state)).toBe(true)
  })

  it('exposes the address a cabled machine should be given', () => {
    applyState(state({ gateway_address: '10.10.10.1' }))

    expect(gatewayAddress(wiredStore.state)).toBe('10.10.10.1')
  })

  it.each([
    ['NetworkManager is unreachable', { available: false }],
    ['host network control is off', { control_enabled: false }],
    ['no console password is set', { console_password_set: false }],
  ])('refuses to enable controls while %s', (_label, overrides) => {
    applyState(state(overrides))

    expect(canMutate(wiredStore.state)).toBe(false)
  })

  it('enables controls when all three preconditions hold', () => {
    applyState(state())

    expect(canMutate(wiredStore.state)).toBe(true)
  })
})

describe('resetTransientState', () => {
  it('clears a stale failure without dropping the state itself', () => {
    // A message left standing would greet the operator on their next visit,
    // describing an attempt they have long forgotten.
    applyState(state())
    recordError(apiError({ code: 'wired_busy' }), 'fallback')

    resetTransientState()

    expect(wiredStore.state.errorMessage).toBeNull()
    expect(wiredStore.state.errorCode).toBeNull()
    expect(wiredStore.state.errorCommandOutput).toBeNull()
    expect(wiredStore.state.state).not.toBeNull()
  })
})

describe('refresh', () => {
  it('loads the state and the port list together', async () => {
    vi.spyOn(apiClient, 'getWired').mockResolvedValue(state({ interface: 'eth0' }))
    vi.spyOn(apiClient, 'getWiredInterfaces').mockResolvedValue({
      interfaces: [{ name: 'eth0', state: 'connected' }],
      generated_at: 0,
    } as never)
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({
      clients: [],
      generated_at: 0,
    } as never)

    await refresh()

    expect(wiredStore.state.state?.interface).toBe('eth0')
    expect(wiredStore.state.interfaces).toHaveLength(1)
    expect(wiredStore.state.errorMessage).toBeNull()
  })

  it('records a failure rather than leaving the panel on "loading" forever', async () => {
    vi.spyOn(apiClient, 'getWired').mockRejectedValue(apiError({ code: 'wired_unavailable' }, 503))
    vi.spyOn(apiClient, 'getWiredInterfaces').mockResolvedValue({
      interfaces: [],
      generated_at: 0,
    } as never)
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({
      clients: null,
      generated_at: 0,
    } as never)

    await refresh()

    expect(wiredStore.state.phase).toBe('failed')
    expect(wiredStore.state.errorCode).toBe('wired_unavailable')
  })
})

describe('refreshClients', () => {
  it('preserves null as "cannot tell" rather than collapsing it to empty', async () => {
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({
      clients: null,
      generated_at: 0,
    } as never)

    await refreshClients()

    expect(wiredStore.state.clients).toBeNull()
  })

  it('keeps an empty list distinct from null', async () => {
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({
      clients: [],
      generated_at: 0,
    } as never)

    await refreshClients()

    expect(wiredStore.state.clients).toEqual([])
  })

  it('treats an absent key as "cannot tell", not as an empty list', async () => {
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({ generated_at: 0 } as never)

    await refreshClients()

    expect(wiredStore.state.clients).toBeNull()
  })

  it('never blanks the settings form when the lease read fails', async () => {
    applyState(state())
    vi.spyOn(apiClient, 'getWiredClients').mockRejectedValue(new Error('boom'))

    await refreshClients()

    expect(wiredStore.state.clients).toBeNull()
    // The form's own state survives — the list is supplementary.
    expect(wiredStore.state.state).not.toBeNull()
    expect(wiredStore.state.errorMessage).toBeNull()
  })
})

describe('mutations', () => {
  beforeEach(() => {
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({
      clients: [],
      generated_at: 0,
    } as never)
  })

  it('saves and applies the state the server hands back', async () => {
    vi.spyOn(apiClient, 'putWired').mockResolvedValue(state({ active: true }))

    const saved = await save({ enabled: true, confirm_uplink_loss: true })

    expect(saved).toBe(true)
    expect(wiredStore.state.state?.active).toBe(true)
    expect(wiredStore.state.phase).toBe('form')
  })

  it('announces a save that only stores settings differently from one that starts', async () => {
    // "Saved" and "saved and started" are different events, and a screen-reader
    // user has nothing but the announcement to tell them which one happened.
    vi.spyOn(apiClient, 'putWired').mockResolvedValue(state({ active: false }))

    expect(await save({ enabled: false, confirm_uplink_loss: false })).toBe(true)
    expect(wiredStore.state.state?.active).toBe(false)
  })

  it('reports a refused save without applying anything', async () => {
    vi.spyOn(apiClient, 'putWired').mockRejectedValue(
      apiError({ code: 'uplink_loss_unconfirmed' }, 409),
    )

    const saved = await save({ enabled: true, confirm_uplink_loss: false })

    expect(saved).toBe(false)
    expect(wiredStore.state.errorCode).toBe('uplink_loss_unconfirmed')
    expect(wiredStore.state.state).toBeNull()
  })

  it('carries the uplink acknowledgement through to enable', async () => {
    // The check the operator ticked must be the one the server is told about.
    const enableWired = vi
      .spyOn(apiClient, 'enableWired')
      .mockResolvedValue(state({ active: true, pending_confirmation: true }))

    await enable(true)

    expect(enableWired).toHaveBeenCalledWith({ confirm_uplink_loss: true })
    expect(wiredStore.state.phase).toBe('awaiting-confirm')
  })

  it('carries the uplink acknowledgement through to disable', async () => {
    const disableWired = vi.spyOn(apiClient, 'disableWired').mockResolvedValue(state())

    await disable(true)

    expect(disableWired).toHaveBeenCalledWith({ confirm_uplink_loss: true })
  })

  it('reports a failed enable', async () => {
    vi.spyOn(apiClient, 'enableWired').mockRejectedValue(apiError({ code: 'wired_busy' }, 409))

    expect(await enable(false)).toBe(false)
    expect(wiredStore.state.errorCode).toBe('wired_busy')
  })

  it('reports a failed disable', async () => {
    vi.spyOn(apiClient, 'disableWired').mockRejectedValue(apiError({ code: 'wired_busy' }, 409))

    expect(await disable(false)).toBe(false)
  })

  it('confirms a share that is on trial', async () => {
    vi.spyOn(apiClient, 'confirmWired').mockResolvedValue(state({ active: true, enabled: true }))

    expect(await confirm()).toBe(true)
    expect(wiredStore.state.state?.enabled).toBe(true)
  })

  it('reports a confirmation that arrived too late', async () => {
    vi.spyOn(apiClient, 'confirmWired').mockRejectedValue(
      apiError({ code: 'no_pending_confirmation' }, 409),
    )

    expect(await confirm()).toBe(false)
    expect(wiredStore.state.errorMessage).toContain('already rolled back')
  })

  it('re-reads everything after forgetting the configuration', async () => {
    vi.spyOn(apiClient, 'deleteWired').mockResolvedValue(undefined as never)
    vi.spyOn(apiClient, 'getWired').mockResolvedValue(state({ configured: false }))
    vi.spyOn(apiClient, 'getWiredInterfaces').mockResolvedValue({
      interfaces: [],
      generated_at: 0,
    } as never)

    expect(await forget()).toBe(true)
    expect(wiredStore.state.state?.configured).toBe(false)
  })

  it('reports a failed forget', async () => {
    vi.spyOn(apiClient, 'deleteWired').mockRejectedValue(
      apiError({ code: 'wired_unavailable' }, 503),
    )

    expect(await forget()).toBe(false)
    expect(wiredStore.state.errorCode).toBe('wired_unavailable')
  })

  it('re-reads the lease list after a release rather than removing the row', async () => {
    // The server decides whether the release took; a row that vanished
    // optimistically would claim more than the response does.
    const releaseWiredLease = vi
      .spyOn(apiClient, 'releaseWiredLease')
      .mockResolvedValue(undefined as never)

    expect(await releaseLease('aa:bb:cc:dd:ee:ff')).toBe(true)
    expect(releaseWiredLease).toHaveBeenCalledWith('aa:bb:cc:dd:ee:ff')
    expect(wiredStore.state.clients).toEqual([])
  })

  it('reports a refused release', async () => {
    vi.spyOn(apiClient, 'releaseWiredLease').mockRejectedValue(
      apiError({ code: 'wired_not_running' }, 409),
    )

    expect(await releaseLease('aa:bb:cc:dd:ee:ff')).toBe(false)
    expect(wiredStore.state.errorCode).toBe('wired_not_running')
  })
})

describe('handleRollbackNotice', () => {
  it('announces assertively and re-reads the state', async () => {
    // The rollback happened on the server's timer with nobody watching, and it
    // means the network the operator was about to rely on is gone.
    const getWired = vi.spyOn(apiClient, 'getWired').mockResolvedValue(state({ active: false }))
    vi.spyOn(apiClient, 'getWiredInterfaces').mockResolvedValue({
      interfaces: [],
      generated_at: 0,
    } as never)
    vi.spyOn(apiClient, 'getWiredClients').mockResolvedValue({
      clients: null,
      generated_at: 0,
    } as never)

    handleRollbackNotice('Wired sharing was not confirmed in time and has been rolled back.')
    await vi.waitFor(() => {
      expect(getWired).toHaveBeenCalled()
    })

    expect(document.getElementById('live-region-assertive')?.textContent).toContain('rolled back')
  })
})
