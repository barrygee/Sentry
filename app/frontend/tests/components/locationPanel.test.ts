import { axe } from 'jest-axe'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient, type SentryLocation } from '../../src/api/client.js'
import type { Component } from '../../src/core/component.js'
import { locationPanel } from '../../src/components/location/locationPanel.js'
import { locationStore } from '../../src/state/locationStore.js'

/**
 * Tests for the Sentry Location settings panel.
 *
 * Two obligations are asserted here that nothing else covers: the panel must
 * refuse to send half a position (a lone coordinate is unplottable, and the
 * server would answer with a 422 that names the pair rather than the empty
 * box), and a rejected save must move focus to the field at fault — otherwise
 * a screen-reader user is told something is wrong and never taken to it.
 */

const LATITUDE = 54.95149
const LONGITUDE = -1.53586

let panel: Component<void>

function serverLocation(overrides: Partial<SentryLocation> = {}): SentryLocation {
  return { latitude: LATITUDE, longitude: LONGITUDE, updated_at: 1, ...overrides } as SentryLocation
}

function panelText(): string {
  return (panel.element.textContent ?? '').replace(/\s+/g, ' ').trim()
}

/**
 * The text an operator can actually see.
 *
 * `textContent` alone includes the notice boxes that are present but hidden
 * (`display: none`), so asserting on it would pass whether or not the
 * confirmation was showing — which is the very thing these tests check.
 */
function visibleText(node: Node = panel.element): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? ''
  }
  if (node instanceof HTMLElement && node.style.display === 'none') {
    return ''
  }
  return [...node.childNodes]
    .map((child) => visibleText(child))
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function field(label: 'Lat' | 'Lon'): HTMLInputElement {
  const labels = [...panel.element.querySelectorAll('label')]
  const match = labels.find((candidate) => candidate.textContent?.trim() === label)
  if (!match) throw new Error(`no field labelled ${label}`)
  const input = panel.element.querySelector<HTMLInputElement>(`#${match.htmlFor}`)
  if (!input) throw new Error(`no input for ${label}`)
  return input
}

/** Blur a field, which is when the panel validates that box on its own. */
function blur(label: 'Lat' | 'Lon'): void {
  field(label).dispatchEvent(new Event('blur', { bubbles: true }))
}

/** Type into a field the way the operator does, firing the `input` event the component listens for. */
function typeInto(label: 'Lat' | 'Lon', value: string): void {
  const input = field(label)
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

async function save(): Promise<void> {
  panel.element.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true }))
  // Two turns: one for the submit handler's await, one for the store's
  // microtask-coalesced notification.
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

/** Put the store into a settled state and let the panel adopt it. */
async function storeSettled(overrides: Partial<typeof locationStore.state> = {}): Promise<void> {
  locationStore.setState({ phase: 'idle', errorMessage: null, ...overrides })
  await Promise.resolve()
}

beforeEach(() => {
  document.body.innerHTML = `
    <div id="live-region-polite"></div>
    <div id="live-region-assertive"></div>
  `
  locationStore.setState({
    latitude: null,
    longitude: null,
    updatedAt: 0,
    phase: 'loading',
    errorMessage: null,
  })
  panel = locationPanel()
  document.body.appendChild(panel.element)
})

afterEach(() => {
  panel.destroy()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('locationPanel', () => {
  it('is a labelled section, not a dialog', () => {
    const section = panel.element
    expect(section.tagName).toBe('SECTION')
    expect(section.getAttribute('aria-labelledby')).toBeTruthy()
  })

  it('is headed Sentry Location', () => {
    const heading = panel.element.querySelector('h2')
    expect(heading?.textContent?.trim()).toBe('Sentry Location')
  })

  it('explains what the coordinates are for', () => {
    expect(panelText()).toMatch(/Set a fixed latitude \/ longitude for this Sentry/)
  })

  it('offers a latitude and a longitude field', () => {
    expect(field('Lat')).toBeTruthy()
    expect(field('Lon')).toBeTruthy()
  })

  it('says so when no position is set', async () => {
    await storeSettled()

    expect(panelText()).toMatch(/No position set/)
  })

  it('shows when the position was last set', async () => {
    await storeSettled({ latitude: LATITUDE, longitude: LONGITUDE, updatedAt: 1_700_000_000_000 })

    expect(panelText()).toMatch(/Last set/)
  })

  it('pre-fills the fields from the stored position', async () => {
    await storeSettled({ latitude: LATITUDE, longitude: LONGITUDE, updatedAt: 1 })

    expect(field('Lat').value).toBe(String(LATITUDE))
    expect(field('Lon').value).toBe(String(LONGITUDE))
  })

  describe('validation before the request', () => {
    it('refuses to send a latitude with no longitude', async () => {
      const put = vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation())
      await storeSettled()

      typeInto('Lat', String(LATITUDE))
      await save()

      expect(put).not.toHaveBeenCalled()
      expect(visibleText()).toMatch(/Enter a longitude too/)
    })

    it('refuses to send a longitude with no latitude', async () => {
      const put = vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation())
      await storeSettled()

      typeInto('Lon', String(LONGITUDE))
      await save()

      expect(put).not.toHaveBeenCalled()
      expect(visibleText()).toMatch(/Enter a latitude too/)
    })

    it('refuses to send a coordinate off the globe', async () => {
      const put = vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation())
      await storeSettled()

      typeInto('Lat', '91')
      typeInto('Lon', '0')
      await save()

      expect(put).not.toHaveBeenCalled()
      expect(panelText()).toMatch(/between -90 and 90/)
    })

    it('marks the offending field invalid for assistive tech', async () => {
      await storeSettled()

      typeInto('Lat', '91')
      typeInto('Lon', '0')
      await save()

      expect(field('Lat').getAttribute('aria-invalid')).toBe('true')
      expect(field('Lon').getAttribute('aria-invalid')).toBeNull()
    })

    it('moves focus to the empty field when only half a pair was given', async () => {
      await storeSettled()

      typeInto('Lat', String(LATITUDE))
      await save()

      expect(document.activeElement).toBe(field('Lon'))
    })

    it('moves focus to the out-of-range field', async () => {
      await storeSettled()

      typeInto('Lat', '91')
      typeInto('Lon', '0')
      await save()

      expect(document.activeElement).toBe(field('Lat'))
    })

    it('clears a complaint as the operator retypes', async () => {
      await storeSettled()
      typeInto('Lat', '91')
      typeInto('Lon', '0')
      await save()

      typeInto('Lat', '54')
      await Promise.resolve()

      expect(field('Lat').getAttribute('aria-invalid')).toBeNull()
    })
  })

  describe('validating on blur', () => {
    // Commit-on-blur, so an operator who tabs away from a bad coordinate is
    // told immediately rather than at submit time.
    it('complains about an out-of-range latitude when the field is left', async () => {
      await storeSettled()

      typeInto('Lat', '91')
      blur('Lat')
      await Promise.resolve()

      expect(visibleText()).toMatch(/between -90 and 90/)
      expect(field('Lat').getAttribute('aria-invalid')).toBe('true')
    })

    it('complains about an out-of-range longitude when the field is left', async () => {
      await storeSettled()

      typeInto('Lon', '181')
      blur('Lon')
      await Promise.resolve()

      expect(visibleText()).toMatch(/between -180 and 180/)
      expect(field('Lon').getAttribute('aria-invalid')).toBe('true')
    })

    it('says nothing about a field left blank', async () => {
      // Blank is a valid value — it is half of how a position is cleared — so
      // tabbing through an empty field must not accuse the operator of anything.
      await storeSettled()

      blur('Lat')
      await Promise.resolve()

      expect(field('Lat').getAttribute('aria-invalid')).toBeNull()
    })

    it('accepts a valid coordinate on blur', async () => {
      await storeSettled()

      typeInto('Lat', String(LATITUDE))
      blur('Lat')
      await Promise.resolve()

      expect(field('Lat').getAttribute('aria-invalid')).toBeNull()
    })
  })

  describe('lifecycle', () => {
    it('is store-driven, so update() is a no-op', () => {
      expect(() => panel.update()).not.toThrow()
    })

    it('stops responding to the store once destroyed', async () => {
      panel.destroy()

      locationStore.setState({ latitude: 1, longitude: 2, phase: 'idle', updatedAt: 99 })
      await Promise.resolve()

      // A panel that kept its subscription would keep writing into detached
      // DOM every time the store changed, for the life of the page.
      expect(panelText()).not.toMatch(/Last set/)
    })
  })

  describe('saving', () => {
    it('sends a complete pair', async () => {
      const put = vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation())
      await storeSettled()

      typeInto('Lat', String(LATITUDE))
      typeInto('Lon', String(LONGITUDE))
      await save()

      expect(put).toHaveBeenCalledWith({ latitude: LATITUDE, longitude: LONGITUDE })
    })

    it('sends two nulls when both fields are cleared', async () => {
      const put = vi
        .spyOn(apiClient, 'putLocation')
        .mockResolvedValue(serverLocation({ latitude: null, longitude: null }))
      await storeSettled({ latitude: LATITUDE, longitude: LONGITUDE, updatedAt: 1 })

      typeInto('Lat', '')
      typeInto('Lon', '')
      await save()

      expect(put).toHaveBeenCalledWith({ latitude: null, longitude: null })
    })

    it('confirms a successful save', async () => {
      vi.spyOn(apiClient, 'putLocation').mockResolvedValue(serverLocation())
      await storeSettled()

      typeInto('Lat', String(LATITUDE))
      typeInto('Lon', String(LONGITUDE))
      await save()

      expect(visibleText()).toMatch(/Location saved/)
    })

    it('shows the server’s rejection rather than claiming success', async () => {
      vi.spyOn(apiClient, 'putLocation').mockRejectedValue(
        Object.assign(new Error('boom'), { name: 'ApiError' }),
      )
      await storeSettled()

      typeInto('Lat', String(LATITUDE))
      typeInto('Lon', String(LONGITUDE))
      await save()

      expect(visibleText()).not.toMatch(/Location saved/)
      expect(visibleText()).toMatch(/could not be saved/)
    })

    it('does not overwrite a half-typed field with the stored value', async () => {
      // A background refresh landing mid-edit must not eat keystrokes.
      await storeSettled({ latitude: LATITUDE, longitude: LONGITUDE, updatedAt: 1 })
      typeInto('Lat', '12.3')

      await storeSettled({ latitude: LATITUDE, longitude: LONGITUDE, updatedAt: 2 })

      expect(field('Lat').value).toBe('12.3')
    })
  })

  it('has no accessibility violations', async () => {
    await storeSettled({ latitude: LATITUDE, longitude: LONGITUDE, updatedAt: 1 })

    expect(await axe(panel.element)).toHaveNoViolations()
  })

  it('has no accessibility violations while showing an error', async () => {
    await storeSettled()
    typeInto('Lat', '91')
    typeInto('Lon', '0')
    await save()

    expect(await axe(panel.element)).toHaveNoViolations()
  })
})
