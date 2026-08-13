import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiClient, type SentryLocation } from '../../src/api/client.js'
import {
  hasLocation,
  locationStore,
  refreshLocation,
  resetTransientState,
  saveLocation,
} from '../../src/state/locationStore.js'

/**
 * Tests for the Sentry Location store.
 *
 * The behaviour worth pinning is what happens when the server *rejects* a
 * write: the stored position must not move. A store that optimistically
 * adopted the attempted coordinates would leave the console showing a location
 * that no Sentinel has, which is worse than showing none.
 */

const LATITUDE = 54.95149
const LONGITUDE = -1.53586

function serverLocation(overrides: Partial<SentryLocation> = {}): SentryLocation {
  return {
    latitude: LATITUDE,
    longitude: LONGITUDE,
    updated_at: 1_700_000_000_000,
    ...overrides,
  } as SentryLocation
}

function rejection(message: string, status = 422): ApiError {
  return new ApiError(status, { code: 'validation_error', message }, 'fallback')
}

function resetStore(): void {
  locationStore.setState({
    latitude: null,
    longitude: null,
    updatedAt: 0,
    phase: 'loading',
    errorMessage: null,
  })
}

beforeEach(resetStore)
afterEach(() => {
  vi.restoreAllMocks()
})

describe('hasLocation', () => {
  it('is false before a position is set', () => {
    expect(hasLocation(locationStore.state)).toBe(false)
  })

  it('is true once both coordinates are stored', () => {
    locationStore.setState({ latitude: LATITUDE, longitude: LONGITUDE })

    expect(hasLocation(locationStore.state)).toBe(true)
  })

  it('is true at zero, which is a real position', () => {
    locationStore.setState({ latitude: 0, longitude: 0 })

    expect(hasLocation(locationStore.state)).toBe(true)
  })

  it('is false while only one coordinate is present', () => {
    locationStore.setState({ latitude: LATITUDE, longitude: null })

    expect(hasLocation(locationStore.state)).toBe(false)
  })
})

describe('refreshLocation', () => {
  it('adopts the stored position', async () => {
    vi.spyOn(apiClient, 'getLocation').mockResolvedValue(serverLocation())

    await refreshLocation()

    expect(locationStore.state.latitude).toBe(LATITUDE)
    expect(locationStore.state.longitude).toBe(LONGITUDE)
    expect(locationStore.state.updatedAt).toBe(1_700_000_000_000)
    expect(locationStore.state.phase).toBe('idle')
  })

  it('reports an unset position as null rather than zero', async () => {
    vi.spyOn(apiClient, 'getLocation').mockResolvedValue(
      serverLocation({ latitude: null, longitude: null, updated_at: 0 }),
    )

    await refreshLocation()

    expect(locationStore.state.latitude).toBeNull()
    expect(hasLocation(locationStore.state)).toBe(false)
  })

  it('treats an absent coordinate key as unset rather than undefined', async () => {
    // The response is typed, but it comes off the wire: an older Sentry that
    // predates this field sends no key at all, and `undefined` leaking into the
    // store would render as an empty field that still claims a position.
    vi.spyOn(apiClient, 'getLocation').mockResolvedValue({} as SentryLocation)

    await refreshLocation()

    expect(locationStore.state.latitude).toBeNull()
    expect(locationStore.state.longitude).toBeNull()
    expect(locationStore.state.updatedAt).toBe(0)
  })

  it('surfaces a failure instead of silently showing no position', async () => {
    vi.spyOn(apiClient, 'getLocation').mockRejectedValue(rejection('Nope', 500))

    await refreshLocation()

    expect(locationStore.state.phase).toBe('failed')
    expect(locationStore.state.errorMessage).toBe('Nope')
  })

  it('falls back to its own wording when the server sent no message', async () => {
    vi.spyOn(apiClient, 'getLocation').mockRejectedValue(new Error('network down'))

    await refreshLocation()

    expect(locationStore.state.errorMessage).toMatch(/Could not read/)
  })

  it('clears a previous error once a read succeeds', async () => {
    locationStore.setState({ phase: 'failed', errorMessage: 'stale complaint' })
    vi.spyOn(apiClient, 'getLocation').mockResolvedValue(serverLocation())

    await refreshLocation()

    expect(locationStore.state.errorMessage).toBeNull()
  })
})

describe('saveLocation', () => {
  it('sends both coordinates and reports success', async () => {
    const put = vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation())

    const saved = await saveLocation(LATITUDE, LONGITUDE)

    expect(saved).toBe(true)
    expect(put).toHaveBeenCalledWith({ latitude: LATITUDE, longitude: LONGITUDE })
  })

  it('adopts what the server stored, not what was sent', async () => {
    // The server is the authority: if it normalises a value, that is what the
    // operator must be left looking at.
    vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation({ latitude: 54.9515 }))

    await saveLocation(LATITUDE, LONGITUDE)

    expect(locationStore.state.latitude).toBe(54.9515)
  })

  it('sends two nulls to clear the position', async () => {
    const put = vi
      .spyOn(apiClient, 'putLocation')
      .mockResolvedValue(serverLocation({ latitude: null, longitude: null }))

    await saveLocation(null, null)

    expect(put).toHaveBeenCalledWith({ latitude: null, longitude: null })
    expect(hasLocation(locationStore.state)).toBe(false)
  })

  it('treats an absent coordinate key in the save response as unset', async () => {
    vi.spyOn(apiClient, 'putLocation').mockResolvedValue({} as SentryLocation)

    await saveLocation(null, null)

    expect(locationStore.state.latitude).toBeNull()
    expect(locationStore.state.updatedAt).toBe(0)
  })

  it('leaves the stored position untouched when the server rejects the write', async () => {
    locationStore.setState({ latitude: 1, longitude: 2, phase: 'idle' })
    vi.spyOn(apiClient, 'putLocation').mockRejectedValue(rejection('Off the globe.'))

    const saved = await saveLocation(91, 0)

    expect(saved).toBe(false)
    expect(locationStore.state.latitude).toBe(1)
    expect(locationStore.state.longitude).toBe(2)
  })

  it('shows the server’s own rejection message', async () => {
    vi.spyOn(apiClient, 'putLocation').mockRejectedValue(rejection('Off the globe.'))

    await saveLocation(91, 0)

    expect(locationStore.state.errorMessage).toBe('Off the globe.')
    expect(locationStore.state.phase).toBe('failed')
  })

  it('falls back to its own wording when the server sent no message', async () => {
    vi.spyOn(apiClient, 'putLocation').mockRejectedValue(new Error('network down'))

    await saveLocation(LATITUDE, LONGITUDE)

    expect(locationStore.state.errorMessage).toMatch(/could not be saved/)
  })
})

describe('resetTransientState', () => {
  it('drops a failed attempt’s error', () => {
    locationStore.setState({ phase: 'failed', errorMessage: 'boom' })

    resetTransientState()

    expect(locationStore.state.errorMessage).toBeNull()
    expect(locationStore.state.phase).toBe('idle')
  })

  it('keeps the saved position, which is not transient', () => {
    locationStore.setState({
      latitude: LATITUDE,
      longitude: LONGITUDE,
      phase: 'failed',
      errorMessage: 'boom',
    })

    resetTransientState()

    expect(locationStore.state.latitude).toBe(LATITUDE)
  })

  it('leaves a clean store alone', () => {
    locationStore.setState({ phase: 'idle', errorMessage: null })

    resetTransientState()

    expect(locationStore.state.phase).toBe('idle')
  })
})
