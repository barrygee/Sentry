import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { HotspotState } from '../../src/api/client.js'
import type { Component } from '../../src/core/component.js'
import { hotspotDialog } from '../../src/components/hotspot/hotspotDialog.js'
import { hotspotStore, type HotspotPhase } from '../../src/state/hotspotStore.js'

/**
 * Tests that the hotspot dialog can always be dismissed.
 *
 * It could not. The only Close control lived in the form's action row, and the
 * form renders only when the hotspot is manageable — so the three states that
 * render no form (hotspot control disabled in `.env`, no auth token,
 * NetworkManager unreachable) presented a modal with no visible way out.
 *
 * Those are not edge cases. They are what a fresh Pi shows the first time an
 * operator opens the panel, which is exactly when they most need to back out.
 * `Escape` still worked, but a modal whose only dismissal is an invisible
 * keystroke is not dismissible in any sense that matters.
 */

/** A `HotspotState` with everything healthy; each test spoils one field. */
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

async function showDialog(state: HotspotState, phase: HotspotPhase = 'form'): Promise<void> {
  hotspotStore.setState({ state, phase, dialogOpen: true, interfaces: [], clients: null })
  // Store notifications are coalesced to a microtask.
  await Promise.resolve()
}

/** Every enabled or disabled button currently rendered, by accessible text. */
function buttonsNamed(name: string): HTMLButtonElement[] {
  return Array.from(document.body.querySelectorAll('button')).filter(
    (button) => (button.textContent ?? '').trim().toLowerCase() === name.toLowerCase(),
  )
}

let dialog: Component<void>

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
    dialogOpen: false,
  })
  dialog = hotspotDialog()
})

afterEach(() => {
  dialog.destroy()
  hotspotStore.setState({ dialogOpen: false })
  document.body.innerHTML = ''
})

describe('hotspotDialog dismissal', () => {
  it.each([
    ['hotspot control disabled in .env', { control_enabled: false }],
    ['no API auth token configured', { auth_token_configured: false }],
    ['NetworkManager unreachable', { available: false }],
  ])('offers a Close control when %s', async (_label, overrides) => {
    await showDialog(healthyState(overrides))

    expect(buttonsNamed('Close')).toHaveLength(1)
  })

  it('offers a Close control in the healthy, manageable state too', async () => {
    await showDialog(healthyState())

    expect(buttonsNamed('Close')).toHaveLength(1)
  })

  it('renders exactly one Close, not one per surface', async () => {
    // The fix moved Close out of the form and onto the dialog. Leaving both
    // would put two identical controls side by side whenever the form shows.
    await showDialog(healthyState({ configured: true, passphrase_set: true }))

    expect(buttonsNamed('Close')).toHaveLength(1)
  })

  it('closes the dialog when Close is pressed', async () => {
    await showDialog(healthyState({ control_enabled: false }))
    const closeButton = buttonsNamed('Close')[0]
    expect(closeButton).toBeDefined()

    closeButton?.click()
    await Promise.resolve()

    expect(hotspotStore.state.dialogOpen).toBe(false)
  })

  it('disables Close while a change awaits confirmation', async () => {
    // Deliberate: walking away mid-countdown abandons a network change already
    // applied to the hardware, which is what the countdown exists to prevent.
    // The button mirrors the dialog's own `disableDismiss` rather than
    // overriding it.
    await showDialog(healthyState({ pending_confirmation: true }), 'awaiting-confirm')

    expect(buttonsNamed('Close')[0]?.disabled).toBe(true)
  })

  it('disables Close while a request is in flight', async () => {
    await showDialog(healthyState(), 'submitting')

    expect(buttonsNamed('Close')[0]?.disabled).toBe(true)
  })

  it('re-enables Close once the request settles', async () => {
    await showDialog(healthyState(), 'submitting')
    expect(buttonsNamed('Close')[0]?.disabled).toBe(true)

    await showDialog(healthyState(), 'form')

    expect(buttonsNamed('Close')[0]?.disabled).toBe(false)
  })
})
