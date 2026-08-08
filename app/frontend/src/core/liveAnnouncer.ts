/**
 * The two live regions the shell declares once in `index.html` (architecture
 * §9.4): a debounced/coalesced `polite` region for plug/unplug and state
 * changes, and an immediate `role="alert"` region for errors and serial-flash
 * outcomes.
 *
 * A module-level singleton writing straight into those two nodes, so every
 * caller announces through the same regions rather than mounting its own.
 * Ported from the retired `useLiveAnnouncer` composable with its debounce,
 * forced-flush ceiling and coalescing rules intact.
 */

const DEFAULT_COALESCE_MS = 500
/**
 * A forced flush ceiling: without this, a sustained burst of events arriving
 * faster than `coalesceMs` apart keeps rescheduling the debounce timer
 * indefinitely, so *nothing* is announced for the whole burst — the worst
 * possible outcome for a live region. `announcePolite` shrinks its own delay as
 * this deadline approaches so a flush always happens by then.
 */
const DEFAULT_MAX_WAIT_MS = 1_800
/** Cap on how many distinct updates are read out individually before the rest are summarised. */
const MAX_COALESCED_ITEMS = 5

export interface LiveAnnouncer {
  /** Queue a polite announcement; coalesced with any other call within the debounce window. */
  announcePolite(message: string): void
  /** Announce immediately and unconditionally — errors and serial-flash outcomes only. */
  announceAssertive(message: string): void
}

let sharedAnnouncer: LiveAnnouncer | null = null

/** Returns the shared announcer, binding it to the regions in `index.html` on first use. */
export function liveAnnouncer(): LiveAnnouncer {
  sharedAnnouncer ??= createLiveAnnouncer(
    requireRegion('live-region-polite'),
    requireRegion('live-region-assertive'),
    DEFAULT_COALESCE_MS,
    DEFAULT_MAX_WAIT_MS,
  )
  return sharedAnnouncer
}

function requireRegion(elementId: string): HTMLElement {
  const region = document.getElementById(elementId)
  if (!region) {
    throw new Error(`Missing live region #${elementId} in index.html`)
  }
  return region
}

export function createLiveAnnouncer(
  politeRegion: HTMLElement,
  assertiveRegion: HTMLElement,
  coalesceMs: number,
  maxWaitMs: number,
): LiveAnnouncer {
  let pendingMessages: string[] = []
  let flushTimeoutId: ReturnType<typeof setTimeout> | null = null
  let firstPendingAtMs: number | null = null

  function flushPolite(): void {
    flushTimeoutId = null
    firstPendingAtMs = null
    if (pendingMessages.length === 0) {
      return
    }
    const [firstMessage] = pendingMessages
    politeRegion.textContent =
      pendingMessages.length === 1 && firstMessage !== undefined
        ? firstMessage
        : coalesceMessages(pendingMessages)
    pendingMessages = []
  }

  return {
    announcePolite(message: string): void {
      if (pendingMessages.length === 0) {
        firstPendingAtMs = Date.now()
      }
      pendingMessages.push(message)
      if (flushTimeoutId !== null) {
        clearTimeout(flushTimeoutId)
      }
      const elapsedMs = firstPendingAtMs === null ? 0 : Date.now() - firstPendingAtMs
      const msUntilForcedFlush = Math.max(maxWaitMs - elapsedMs, 0)
      flushTimeoutId = setTimeout(flushPolite, Math.min(coalesceMs, msUntilForcedFlush))
    },

    announceAssertive(message: string): void {
      // Force a re-announcement even if the text is identical to the last one,
      // since screen readers only announce on a text-content change.
      assertiveRegion.textContent = ''
      queueMicrotask(() => {
        assertiveRegion.textContent = message
      })
    },
  }
}

function coalesceMessages(messages: readonly string[]): string {
  if (messages.length <= MAX_COALESCED_ITEMS) {
    return `${messages.length} device updates: ${messages.join('; ')}`
  }
  const shown = messages.slice(0, MAX_COALESCED_ITEMS)
  const remaining = messages.length - MAX_COALESCED_ITEMS
  return `${messages.length} device updates: ${shown.join('; ')}; and ${remaining} more.`
}
