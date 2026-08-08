/**
 * The store primitive — this app's replacement for Pinia.
 *
 * A store holds one immutable state object and notifies subscribers when it is
 * replaced. It is deliberately not deeply reactive: mutations go through
 * `setState`, which is the only place state changes, so a stray in-place edit
 * cannot silently desynchronise the DOM the way it could with proxy reactivity.
 *
 * Notifications are coalesced to a microtask. Bursts are the normal case here —
 * one SSE `snapshot` frame rewrites every device at once — and without batching
 * each subscriber would run once per field touched.
 */
export type Subscriber<State> = (state: Readonly<State>) => void

export interface Store<State extends object> {
  /** The current state. Treat as frozen — never mutate it in place. */
  readonly state: Readonly<State>
  /** Merges a partial update and schedules a notification. */
  setState(patch: Partial<State> | ((current: Readonly<State>) => Partial<State>)): void
  /** Registers a subscriber. Returns the unsubscribe function. */
  subscribe(subscriber: Subscriber<State>): () => void
}

export function createStore<State extends object>(initialState: State): Store<State> {
  let state: Readonly<State> = Object.freeze({ ...initialState })
  const subscribers = new Set<Subscriber<State>>()
  let notificationScheduled = false

  function notify(): void {
    notificationScheduled = false
    // Snapshot the set first: a subscriber is allowed to unsubscribe (or
    // subscribe) while being notified, and mutating the live set mid-iteration
    // would skip or double-run its neighbours.
    for (const subscriber of [...subscribers]) {
      subscriber(state)
    }
  }

  return {
    get state(): Readonly<State> {
      return state
    },

    setState(patch): void {
      const resolved = typeof patch === 'function' ? patch(state) : patch
      state = Object.freeze({ ...state, ...resolved })
      if (!notificationScheduled) {
        notificationScheduled = true
        queueMicrotask(notify)
      }
    },

    subscribe(subscriber): () => void {
      subscribers.add(subscriber)
      return () => {
        subscribers.delete(subscriber)
      }
    },
  }
}

/**
 * Subscribes to a store and runs `effect` immediately, then on every change —
 * the pattern every mounted component uses to keep itself current.
 *
 * Returns the unsubscribe function, which the component's `destroy` must call.
 */
export function watchStore<State extends object>(
  store: Store<State>,
  effect: Subscriber<State>,
): () => void {
  effect(store.state)
  return store.subscribe(effect)
}
