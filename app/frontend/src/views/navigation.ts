import { setAttribute, setVisible } from '../core/dom.js'

/** The two screens this console has. */
export type Destination = 'devices' | 'settings'

export interface DestinationTarget {
  /** The container to show or hide. */
  view: HTMLElement
  /** The rail button that selects it. */
  navButton: HTMLButtonElement
  /** The heading focus moves to on arrival — the view's accessible name. */
  heading: HTMLElement
  /** Called each time this destination becomes active. Refetch belongs here. */
  onShown?: () => void
  /**
   * Called each time this destination stops being active. Discarding transient,
   * half-finished state belongs here — it is what a dialog's close handler used
   * to do, and losing it would leave a staged import or a stale error waiting
   * to surprise whoever comes back.
   */
  onHidden?: () => void
}

export interface NavigationOptions {
  devices: DestinationTarget
  settings: DestinationTarget
  /**
   * Consulted before every departure. Returning a string blocks the move and
   * the string is announced; returning `null` allows it.
   *
   * This exists because the hotspot's confirmation countdown used to be
   * protected by a modal that refused to close. A section cannot refuse to be
   * navigated away from, so the guard had to move somewhere — and putting it
   * here, rather than inside the panel, keeps the panel ignorant of navigation
   * and keeps the rule in the place that can actually enforce it.
   */
  blockDeparture?: (from: Destination) => string | null
  /** How a blocked departure is announced. Assertive: it is a refusal to act. */
  announce?: (message: string) => void
}

export interface Navigation {
  current: () => Destination
  /** Programmatic navigation. Honours `blockDeparture`. */
  go: (destination: Destination) => void
  destroy: () => void
}

const ACTIVE_CLASSES = ['border-signal-accent', 'bg-signal-accent/[0.08]', 'text-signal-accent']
const INACTIVE_CLASSES = ['border-transparent', 'text-signal-muted', 'hover:text-ink-inverse']

/**
 * Swaps the console between its two destinations.
 *
 * No router and no URL. There are two screens and no deep-linking requirement,
 * so a history integration would be more moving parts than the thing it drives.
 *
 * Two accessibility obligations are met here rather than left to callers,
 * because both are the kind that get forgotten and neither is visible when it
 * is missing:
 *
 * * **Focus follows the destination.** Activating a rail button otherwise
 *   leaves focus on the rail, and a screen-reader user gets no signal that the
 *   entire page changed — the most common way a view swap becomes unusable.
 * * **`aria-current`, not `aria-expanded`.** These buttons navigate; they no
 *   longer disclose. `aria-expanded` would promise something opening in place.
 */
export function createNavigation(options: NavigationOptions): Navigation {
  const targets: Record<Destination, DestinationTarget> = {
    devices: options.devices,
    settings: options.settings,
  }

  let current: Destination = 'devices'

  function paint(destination: Destination): void {
    for (const name of ['devices', 'settings'] as const) {
      const target = targets[name]
      const isActive = name === destination

      setVisible(target.view, isActive)
      target.view.hidden = !isActive

      setAttribute(target.navButton, 'aria-current', isActive ? 'page' : null)
      for (const className of ACTIVE_CLASSES) {
        target.navButton.classList.toggle(className, isActive)
      }
      for (const className of INACTIVE_CLASSES) {
        target.navButton.classList.toggle(className, !isActive)
      }
    }
  }

  function show(destination: Destination, moveFocus: boolean): void {
    if (destination !== current) {
      targets[current].onHidden?.()
    }
    current = destination
    paint(destination)
    targets[destination].onShown?.()
    // Skipped on the initial paint: stealing focus on page load is its own bug.
    if (moveFocus) {
      targets[destination].heading.focus()
    }
  }

  function go(destination: Destination): void {
    if (destination === current) return

    const refusal = options.blockDeparture?.(current) ?? null
    if (refusal !== null) {
      options.announce?.(refusal)
      return
    }

    show(destination, true)
  }

  const listeners: (() => void)[] = []
  for (const name of ['devices', 'settings'] as const) {
    const handler = (): void => go(name)
    targets[name].navButton.addEventListener('click', handler)
    listeners.push(() => targets[name].navButton.removeEventListener('click', handler))
  }

  show('devices', false)

  return {
    current: () => current,
    go,
    destroy(): void {
      for (const remove of listeners) remove()
    },
  }
}
