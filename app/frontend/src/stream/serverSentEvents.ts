import type { ConnectionState } from '../types/sdrs.js'

export type { ConnectionState }

export interface ServerSentEventsOptions {
  /** No event of any kind (the server sends `health` every 5s) within this window forces a reopen. */
  stallTimeoutMs?: number
  /** How long a hidden tab may hold the stream open before it is closed until visible again. */
  hiddenCloseDelayMs?: number
  /** Called when a named event's `data` fails to parse as JSON, instead of throwing. */
  onMalformedEvent?: (eventName: string, raw: string, error: unknown) => void
  /** Injection point for tests — defaults to the real `EventSource` constructor. */
  eventSourceFactory?: (url: string) => EventSource
}

export interface ServerSentEventsHandle {
  /** Current connection state; call `subscribeConnection` to react to changes. */
  getConnection: () => ConnectionState
  /** Registers a listener for connection-state changes. Returns the unsubscribe function. */
  subscribeConnection: (listener: (connection: ConnectionState) => void) => () => void
  getLastEventAt: () => number | null
  close: () => void
  reopen: () => void
}

const DEFAULT_STALL_TIMEOUT_MS = 15_000
const DEFAULT_HIDDEN_CLOSE_DELAY_MS = 60_000

/**
 * Generic, app-agnostic SSE subscription (architecture §9.3). Registers one
 * `addEventListener` per named handler, parses JSON in exactly one place so
 * a malformed frame reports through `onMalformedEvent` instead of throwing
 * into the browser, and layers a stall detector + visibility-aware close on
 * top of the browser's own native reconnect.
 *
 * `url` may be a plain string or a function returning the current URL — the
 * latter lets a caller (like `sdrsStream.ts`) supply a value that changes
 * over time (e.g. once an operator supplies an auth token) without this
 * module depending on any reactivity system. Call `reopen()` after such a
 * change to pick up the new URL.
 */
export function openServerSentEvents(
  url: string | (() => string),
  handlers: Record<string, (data: unknown) => void>,
  options: ServerSentEventsOptions = {},
): ServerSentEventsHandle {
  const stallTimeoutMs = options.stallTimeoutMs ?? DEFAULT_STALL_TIMEOUT_MS
  const hiddenCloseDelayMs = options.hiddenCloseDelayMs ?? DEFAULT_HIDDEN_CLOSE_DELAY_MS
  const createEventSource =
    options.eventSourceFactory ?? ((target: string) => new EventSource(target))

  let connection: ConnectionState = 'connecting'
  let lastEventAt: number | null = null
  const connectionListeners = new Set<(connection: ConnectionState) => void>()

  let eventSource: EventSource | null = null
  let stallIntervalId: ReturnType<typeof setInterval> | null = null
  let hiddenCloseTimeoutId: ReturnType<typeof setTimeout> | null = null
  let manuallyClosed = false

  function currentUrl(): string {
    return typeof url === 'string' ? url : url()
  }

  function setConnection(nextConnection: ConnectionState): void {
    if (connection === nextConnection) return
    connection = nextConnection
    for (const listener of [...connectionListeners]) {
      listener(connection)
    }
  }

  function markEventReceived(): void {
    lastEventAt = Date.now()
    setConnection('live')
  }

  function attachHandlers(source: EventSource): void {
    for (const [eventName, handler] of Object.entries(handlers)) {
      source.addEventListener(eventName, (messageEvent) => {
        const raw = (messageEvent as MessageEvent<string>).data
        markEventReceived()
        try {
          handler(JSON.parse(raw) as unknown)
        } catch (error) {
          options.onMalformedEvent?.(eventName, raw, error)
        }
      })
    }

    source.onopen = () => {
      markEventReceived()
    }

    source.onerror = () => {
      if (manuallyClosed) {
        return
      }
      setConnection(source.readyState === EventSource.CLOSED ? 'offline' : 'reconnecting')
    }
  }

  function open(): void {
    manuallyClosed = false
    setConnection(connection === 'live' ? 'reconnecting' : 'connecting')
    eventSource = createEventSource(currentUrl())
    attachHandlers(eventSource)
  }

  function teardownSource(): void {
    eventSource?.close()
    eventSource = null
  }

  function close(): void {
    manuallyClosed = true
    teardownSource()
    setConnection('offline')
  }

  function reopen(): void {
    teardownSource()
    open()
  }

  function checkForStall(): void {
    if (manuallyClosed || lastEventAt === null) {
      return
    }
    if (Date.now() - lastEventAt > stallTimeoutMs) {
      reopen()
    }
  }

  function handleVisibilityChange(): void {
    if (typeof document === 'undefined') {
      return
    }
    if (document.visibilityState === 'hidden') {
      hiddenCloseTimeoutId = setTimeout(() => {
        if (document.visibilityState === 'hidden') {
          teardownSource()
          setConnection('offline')
        }
      }, hiddenCloseDelayMs)
    } else {
      if (hiddenCloseTimeoutId !== null) {
        clearTimeout(hiddenCloseTimeoutId)
        hiddenCloseTimeoutId = null
      }
      if (eventSource === null && !manuallyClosed) {
        open()
      }
    }
  }

  open()
  stallIntervalId = setInterval(checkForStall, Math.min(stallTimeoutMs, 5_000))
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }

  return {
    getConnection: () => connection,
    subscribeConnection: (listener) => {
      connectionListeners.add(listener)
      return () => {
        connectionListeners.delete(listener)
      }
    },
    getLastEventAt: () => lastEventAt,
    close: () => {
      close()
      if (stallIntervalId !== null) {
        clearInterval(stallIntervalId)
        stallIntervalId = null
      }
      if (hiddenCloseTimeoutId !== null) {
        clearTimeout(hiddenCloseTimeoutId)
        hiddenCloseTimeoutId = null
      }
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange)
      }
    },
    reopen,
  }
}
