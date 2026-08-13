import { apiClient, ApiError } from '../api/client.js'
import { createStore, type Store } from '../core/observable.js'

/**
 * This Sentry's fixed position — the coordinates Sentinel plots it at.
 *
 * The stored value is the *saved* position, never the operator's half-typed
 * one. A draft lives in the panel for as long as the edit does, exactly as the
 * hotspot passphrase and console password do, so a background refresh cannot
 * overwrite a field being typed into.
 */

/** What the panel is currently doing about the position. */
export type LocationPhase = 'loading' | 'idle' | 'saving' | 'failed'

export interface LocationState {
  /** Saved latitude in decimal degrees, or null when no position is set. */
  latitude: number | null
  /** Saved longitude in decimal degrees, or null when no position is set. */
  longitude: number | null
  /** Unix ms the position last changed; 0 when never set. */
  updatedAt: number
  phase: LocationPhase
  /** Operator-facing failure text, or null. */
  errorMessage: string | null
}

export const locationStore: Store<LocationState> = createStore<LocationState>({
  latitude: null,
  longitude: null,
  updatedAt: 0,
  phase: 'loading',
  errorMessage: null,
})

/** Whether a plottable position is stored. Both coordinates or neither. */
export function hasLocation(state: Readonly<LocationState>): boolean {
  return state.latitude !== null && state.longitude !== null
}

/**
 * Read the stored position from the server.
 *
 * Called whenever Settings becomes the active destination. The position can be
 * changed by a config import or another browser, so a panel mounted at boot and
 * never refreshed would show a value that stopped being true.
 */
export async function refreshLocation(): Promise<void> {
  try {
    const location = await apiClient.getLocation()
    locationStore.setState({
      latitude: location.latitude ?? null,
      longitude: location.longitude ?? null,
      updatedAt: location.updated_at ?? 0,
      phase: 'idle',
      errorMessage: null,
    })
  } catch (error) {
    locationStore.setState({
      phase: 'failed',
      errorMessage: messageFor(error, 'Could not read this Sentry’s location.'),
    })
  }
}

/**
 * Save a position, or clear it by passing `null` for both coordinates.
 *
 * Returns whether it landed, so the panel can decide whether to drop its draft.
 * Both coordinates always travel together — the server rejects half a pair, and
 * sending one would only turn a typo into a 422.
 */
export async function saveLocation(
  latitude: number | null,
  longitude: number | null,
): Promise<boolean> {
  locationStore.setState({ phase: 'saving', errorMessage: null })
  try {
    const saved = await apiClient.putLocation({ latitude, longitude })
    locationStore.setState({
      latitude: saved.latitude ?? null,
      longitude: saved.longitude ?? null,
      updatedAt: saved.updated_at ?? 0,
      phase: 'idle',
      errorMessage: null,
    })
    return true
  } catch (error) {
    locationStore.setState({
      phase: 'failed',
      errorMessage: messageFor(error, 'That location could not be saved.'),
    })
    return false
  }
}

/** Drop a failed attempt's error, so leaving and returning to Settings starts clean. */
export function resetTransientState(): void {
  if (locationStore.state.errorMessage !== null || locationStore.state.phase === 'failed') {
    locationStore.setState({ phase: 'idle', errorMessage: null })
  }
}

/** The server's own message when it sent one, else `fallback`. */
function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.detail?.message) {
    return error.detail.message
  }
  return fallback
}
