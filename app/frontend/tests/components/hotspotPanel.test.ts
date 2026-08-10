import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { HotspotState } from '../../src/api/client.js'
import type { Component } from '../../src/core/component.js'
import { hotspotPanel } from '../../src/components/hotspot/hotspotPanel.js'
import { hotspotStore, type HotspotPhase } from '../../src/state/hotspotStore.js'

/**
 * Tests for the hotspot settings section.
 *
 * It was a modal, and its Close control lived inside the form — which renders
 * only when the hotspot is manageable, so the three blocked states presented a
 * dialog with no visible way out. That is fixed by the panel having no chrome
 * to escape from at all, but the underlying obligation survives in a new place:
 * whatever the state, the panel must still say something useful rather than
 * render empty. That is what these assert.
 *
 * The "can I leave?" half now belongs to navigation, and is tested in
 * `tests/views/navigation.test.ts`.
 */

function healthyState(overrides: Partial<HotspotState> = {}): HotspotState {
  return {
    control_enabled: true,
    auth_token_configured: true,
    available: true,
    configured: false,
    enabled: false,
    pending_confirmation: false,
    passphrase_set: false,
    warnings: [],
    ...overrides,
  } as HotspotState
}

async function showState(state: HotspotState | null, phase: HotspotPhase = 'form'): Promise<void> {
  hotspotStore.setState({ state, phase, interfaces: [], clients: null })
  await Promise.resolve()
}

let panel: Component<void>

function panelText(): string {
  return (panel.element.textContent ?? '').replace(/\s+/g, ' ').trim()
}

beforeEach(() => {
  document.body.innerHTML = `
    <div id="live-region-polite"></div>
    <div id="live-region-assertive"></div>
  `
  hotspotStore.setState({
    state: null,
    interfaces: [],
    clients: null,
    phase: 'loading',
    errorMessage: null,
    errorCode: null,
  })
  panel = hotspotPanel()
  document.body.appendChild(panel.element)
})

afterEach(() => {
  panel.destroy()
  document.body.innerHTML = ''
})

describe('hotspotPanel', () => {
  it('is a labelled section, not a dialog', () => {
    // The move off a modal is the point: no role="dialog", and a heading
    // association that lets it sit among sibling sections.
    expect(panel.element.tagName).toBe('SECTION')
    expect(panel.element.getAttribute('role')).toBeNull()
    expect(panel.element.getAttribute('aria-labelledby')).toBeTruthy()
  })

  it('says it is loading before any state arrives', () => {
    expect(panelText()).toContain('Loading hotspot settings')
  })

  it.each([
    // No longer an env var either: hotspot control is a switch in this panel
    // (ADR-0013), so the panel points at itself rather than at a terminal.
    ['hotspot control switched off', { control_enabled: false }, 'Turn it on'],
    // Not an env var any more: the controller password is set in the UI
    // (ADR-0010), so the panel points there rather than at `.env`.
    ['no controller password set', { auth_token_configured: false }, 'controller password'],
    ['NetworkManager unreachable', { available: false }, 'NetworkManager'],
  ])('explains the blockage when %s', async (_label, overrides, expected) => {
    await showState(healthyState(overrides))

    // Never an empty panel: each blocked state names what to do about it.
    expect(panelText()).toContain(expected)
  })

  it('renders the settings form once the hotspot is manageable', async () => {
    await showState(healthyState())

    expect(panel.element.querySelector('form')).not.toBeNull()
  })

  it('renders no form while blocked', async () => {
    await showState(healthyState({ control_enabled: false }))

    expect(panel.element.querySelector('form')).toBeNull()
  })

  it('announces an in-flight save to assistive tech', async () => {
    await showState(healthyState(), 'submitting')

    const status = panel.element.querySelector('[role="status"]')
    expect(status?.textContent).toContain('Applying hotspot settings')
  })

  it('surfaces a failure message in an alert region', async () => {
    hotspotStore.setState({
      state: healthyState(),
      phase: 'failed',
      errorMessage: 'Interface wlan0 is already in use.',
    })
    await Promise.resolve()

    const alert = panel.element.querySelector('[role="alert"]')
    expect(alert?.textContent).toContain('already in use')
  })
})
