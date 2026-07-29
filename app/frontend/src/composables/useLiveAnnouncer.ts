import { ref, type Ref } from 'vue'

export interface LiveAnnouncerHandle {
  /** Bound to the `aria-live="polite"` region's text content. */
  politeMessage: Ref<string>
  /** Bound to the `role="alert"` (assertive) region's text content. */
  assertiveMessage: Ref<string>
  /** Queue a polite announcement; coalesced with any other call within `coalesceMs`. */
  announcePolite: (message: string) => void
  /** Announce immediately and unconditionally — errors and serial-flash outcomes only. */
  announceAssertive: (message: string) => void
}

const DEFAULT_COALESCE_MS = 500

let sharedHandle: LiveAnnouncerHandle | null = null

/**
 * Owns the two live regions the app renders once at its root (architecture
 * §9.4): a debounced/coalesced `polite` region for plug/unplug and state
 * changes, and an immediate `assertive` region for errors and destructive
 * operation outcomes. Returns a module-level singleton so every component
 * announces through the same two DOM nodes rather than each mounting its
 * own — `App.vue` renders the regions once; any component may call
 * `announcePolite`/`announceAssertive` by calling this composable again.
 */
export function useLiveAnnouncer(coalesceMs = DEFAULT_COALESCE_MS): LiveAnnouncerHandle {
  sharedHandle ??= createLiveAnnouncer(coalesceMs)
  return sharedHandle
}

/** Test-only escape hatch so each test file starts from a clean announcer. */
export function resetLiveAnnouncerForTesting(): void {
  sharedHandle = null
}

function createLiveAnnouncer(coalesceMs: number): LiveAnnouncerHandle {
  const politeMessage = ref('')
  const assertiveMessage = ref('')

  let pendingMessages: string[] = []
  let flushTimeoutId: ReturnType<typeof setTimeout> | null = null

  function flushPolite(): void {
    flushTimeoutId = null
    if (pendingMessages.length === 0) {
      return
    }
    const [firstMessage] = pendingMessages
    politeMessage.value =
      pendingMessages.length === 1 && firstMessage !== undefined
        ? firstMessage
        : coalesceMessages(pendingMessages)
    pendingMessages = []
  }

  function announcePolite(message: string): void {
    pendingMessages.push(message)
    if (flushTimeoutId !== null) {
      clearTimeout(flushTimeoutId)
    }
    flushTimeoutId = setTimeout(flushPolite, coalesceMs)
  }

  function announceAssertive(message: string): void {
    // Force a re-announcement even if the text is identical to the last one,
    // since screen readers only announce on a text-content change.
    assertiveMessage.value = ''
    queueMicrotask(() => {
      assertiveMessage.value = message
    })
  }

  return { politeMessage, assertiveMessage, announcePolite, announceAssertive }
}

function coalesceMessages(messages: readonly string[]): string {
  return `${messages.length} device updates: ${messages.join('; ')}`
}
