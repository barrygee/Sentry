import { onScopeDispose, ref, type Ref } from 'vue'

export type ConnectionState = 'connecting' | 'live' | 'reconnecting' | 'offline'

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
  connection: Ref<ConnectionState>
  lastEventAt: Ref<number | null>
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
 */
export function useServerSentEvents(
  url: Ref<string> | string,
  handlers: Record<string, (data: unknown) => void>,
  options: ServerSentEventsOptions = {},
): ServerSentEventsHandle {
  const stallTimeoutMs = options.stallTimeoutMs ?? DEFAULT_STALL_TIMEOUT_MS
  const hiddenCloseDelayMs = options.hiddenCloseDelayMs ?? DEFAULT_HIDDEN_CLOSE_DELAY_MS
  const createEventSource =
    options.eventSourceFactory ?? ((target: string) => new EventSource(target))

  const connection = ref<ConnectionState>('connecting')
  const lastEventAt = ref<number | null>(null)

  let eventSource: EventSource | null = null
  let stallIntervalId: ReturnType<typeof setInterval> | null = null
  let hiddenCloseTimeoutId: ReturnType<typeof setTimeout> | null = null
  let manuallyClosed = false

  function currentUrl(): string {
    return typeof url === 'string' ? url : url.value
  }

  function markEventReceived(): void {
    lastEventAt.value = Date.now()
    connection.value = 'live'
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
      connection.value = source.readyState === EventSource.CLOSED ? 'offline' : 'reconnecting'
    }
  }

  function open(): void {
    manuallyClosed = false
    connection.value = connection.value === 'live' ? 'reconnecting' : 'connecting'
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
    connection.value = 'offline'
  }

  function reopen(): void {
    teardownSource()
    open()
  }

  function checkForStall(): void {
    if (manuallyClosed || lastEventAt.value === null) {
      return
    }
    if (Date.now() - lastEventAt.value > stallTimeoutMs) {
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
          connection.value = 'offline'
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

  onScopeDispose(() => {
    close()
    if (stallIntervalId !== null) {
      clearInterval(stallIntervalId)
    }
    if (hiddenCloseTimeoutId !== null) {
      clearTimeout(hiddenCloseTimeoutId)
    }
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  })

  return { connection, lastEventAt, close, reopen }
}
