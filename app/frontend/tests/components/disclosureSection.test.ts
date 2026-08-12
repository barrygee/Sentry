import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { disclosureSection } from '../../src/components/base/disclosureSection.js'

/**
 * Tests for the disclosure's remembered open state.
 *
 * Boxes start closed, so without persistence an operator would re-open the
 * same two on every visit. The remembered value has to win over `defaultOpen`
 * — the default is only what to do before anyone has expressed a preference.
 *
 * Storage access is guarded rather than assumed: `localStorage` throws outright
 * in a page with cookies blocked, and a disclosure that cannot remember must
 * still open and close.
 */

const STORAGE_KEY = 'sentry.disclosure.test-box'

/**
 * A real in-memory `Storage`.
 *
 * jsdom exposes a `window.localStorage` object with none of the Storage methods
 * on it, so `getItem` is `undefined` and calling it throws. That is a faithful
 * enough stand-in for "storage unavailable" that the component's guard is what
 * keeps this suite from crashing — but it means the *working* path cannot be
 * exercised without supplying a real one here.
 */
function installStorage(): Storage {
  const entries = new Map<string, string>()
  const storage: Storage = {
    get length() {
      return entries.size
    },
    clear: () => entries.clear(),
    getItem: (key) => entries.get(key) ?? null,
    key: (index) => [...entries.keys()][index] ?? null,
    removeItem: (key) => {
      entries.delete(key)
    },
    setItem: (key, value) => {
      entries.set(key, value)
    },
  }
  Object.defineProperty(window, 'localStorage', {
    value: storage,
    configurable: true,
    writable: true,
  })
  return storage
}

/**
 * `Component.element` is typed `HTMLElement` for every component. This one's
 * root is always a `<details>`, so the cast lives here rather than widening the
 * shared contract for one caller's convenience.
 */
function build(options: { persistKey?: string; defaultOpen?: boolean } = {}): {
  element: HTMLDetailsElement
} {
  const section = disclosureSection({
    label: ['A box'],
    children: [],
    ...options,
  })
  return { element: section.element as HTMLDetailsElement }
}

beforeEach(() => {
  installStorage()
})

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('a disclosure that remembers', () => {
  it('starts closed when nothing is remembered and no default is given', () => {
    expect(build({ persistKey: 'test-box' }).element.open).toBe(false)
  })

  it('writes its new state on every toggle', () => {
    const section = build({ persistKey: 'test-box' })
    document.body.appendChild(section.element)

    section.element.open = true
    section.element.dispatchEvent(new Event('toggle'))

    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('open')
  })

  it('reopens on a later mount from what was written', () => {
    window.localStorage.setItem(STORAGE_KEY, 'open')

    expect(build({ persistKey: 'test-box' }).element.open).toBe(true)
  })

  it('lets a remembered closed state override an open default', () => {
    // The direction that matters: a box the operator deliberately shut must
    // stay shut, even though its code asks for open.
    window.localStorage.setItem(STORAGE_KEY, 'closed')

    expect(build({ persistKey: 'test-box', defaultOpen: true }).element.open).toBe(false)
  })

  it('falls back to the default when nothing is remembered', () => {
    expect(build({ persistKey: 'test-box', defaultOpen: true }).element.open).toBe(true)
  })

  it('remembers nothing without a key, so two unkeyed boxes cannot share a state', () => {
    const section = build({})
    document.body.appendChild(section.element)

    section.element.open = true
    section.element.dispatchEvent(new Event('toggle'))

    expect(window.localStorage.length).toBe(0)
  })

  it('still opens and closes when storage throws', () => {
    // Cookies blocked: `localStorage` access itself raises. The control must
    // degrade to forgetful, never to broken.
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('access denied')
      },
    })

    const section = build({ persistKey: 'test-box', defaultOpen: true })
    document.body.appendChild(section.element)

    expect(section.element.open).toBe(true)
    section.element.open = false
    expect(() => section.element.dispatchEvent(new Event('toggle'))).not.toThrow()
  })
})
