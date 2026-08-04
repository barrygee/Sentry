/**
 * Modal focus management, extracted from the retired `BaseDialog.vue` so every
 * dialog still gets identical behaviour from one place: a Tab trap, Escape to
 * dismiss, initial focus on the first focusable control, and focus restored to
 * whatever opened the dialog when it closes.
 *
 * This is the part of the Vue port with the least margin for error — with no
 * framework, nothing else keeps a modal's semantics honest.
 */

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

export interface FocusTrapOptions {
  /** The dialog panel. Must be focusable itself (`tabindex="-1"`) as the fallback target. */
  panel: HTMLElement
  /** Called on Escape, unless dismissal is currently suppressed. */
  onRequestClose: () => void
  /**
   * Suppresses Escape while a destructive action is already committed and in
   * flight, so a stray keypress can never read as "cancelling" hardware that is
   * already being written to. Read on each keypress rather than captured once.
   */
  isDismissSuppressed?: () => boolean
}

export interface FocusTrap {
  /** Moves focus into the dialog and starts trapping. Records the current focus for restoration. */
  activate(): void
  /** Stops trapping and returns focus to whatever held it before `activate`. */
  release(): void
}

export function createFocusTrap(options: FocusTrapOptions): FocusTrap {
  const { panel, onRequestClose, isDismissSuppressed } = options
  let previouslyFocusedElement: HTMLElement | null = null
  let active = false

  function focusableElements(): HTMLElement[] {
    return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (element) => element.offsetParent !== null,
    )
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.stopPropagation()
      if (!isDismissSuppressed?.()) {
        onRequestClose()
      }
      return
    }
    if (event.key !== 'Tab') {
      return
    }

    const focusable = focusableElements()
    if (focusable.length === 0) {
      event.preventDefault()
      return
    }

    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const activeElement = document.activeElement

    if (event.shiftKey && activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }

  return {
    activate(): void {
      if (active) {
        return
      }
      active = true
      previouslyFocusedElement = document.activeElement as HTMLElement | null
      panel.addEventListener('keydown', onKeydown)
      // After a frame, so the panel's content has been laid out and
      // `offsetParent` reports honestly — an element in a display:none subtree
      // is not a valid focus target.
      requestAnimationFrame(() => {
        const [firstFocusable] = focusableElements()
        ;(firstFocusable ?? panel).focus()
      })
    },

    release(): void {
      if (!active) {
        return
      }
      active = false
      panel.removeEventListener('keydown', onKeydown)
      previouslyFocusedElement?.focus()
      previouslyFocusedElement = null
    },
  }
}
