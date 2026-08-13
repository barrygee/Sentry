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

  it('prints the failed command output the response carried', async () => {
    // The panel reads this from the store, not from `state.last_error` — on a
    // failure the state is the pre-request one, whose `last_error` is null.
    hotspotStore.setState({
      state: healthyState({ configured: true }),
      phase: 'failed',
      errorMessage: 'The network command failed.',
      errorCommandOutput: "Error: 'sentry-hotspot' is not an active connection.",
    })
    await Promise.resolve()

    const preformatted = panel.element.querySelector('pre')
    expect(preformatted?.textContent).toContain('is not an active connection')
  })

  it('prints no empty code block when the failure carried no output', async () => {
    hotspotStore.setState({
      state: healthyState({ configured: true }),
      phase: 'failed',
      errorMessage: 'Set a password for the hotspot before enabling it.',
      errorCommandOutput: null,
    })
    await Promise.resolve()

    expect(panel.element.querySelector('pre')).toBeNull()
  })

  it('puts the confirmation countdown directly above the save button', async () => {
    // Not at the top of the panel: it belongs beside the control that caused
    // it, and its two actions read as unrelated to the form from a screen away.
    await showState(
      healthyState({
        configured: true,
        active: true,
        pending_confirmation: true,
        confirm_deadline_ms: Date.now() + 120_000,
      }),
    )

    // Searched across the whole panel, not just the form: the action row now
    // sits after the lease list, which is outside the form element. The
    // ordering is the contract here — where the pair is mounted is not.
    // Matched on the accessible name, not the visible text: the label is now
    // just "Confirm", which is too generic to identify a button by across a
    // whole panel.
    const keepButton = [...panel.element.querySelectorAll('button')].find(
      (button) => button.getAttribute('aria-label') === 'Confirm this hotspot',
    )
    const saveButton = [...panel.element.querySelectorAll('button')].find((button) =>
      /Save hotspot settings/i.test(button.textContent ?? ''),
    )

    expect(keepButton, 'the countdown must render').toBeDefined()
    expect(saveButton).toBeDefined()
    // `compareDocumentPosition` is the ordering check that survives styling:
    // FOLLOWING means save comes after keep in document order.
    expect(
      keepButton!.compareDocumentPosition(saveButton!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('states the condition each toggle puts the network in, not the action', async () => {
    // The toggles sit in the panel header with no field label beside them, so
    // "Hide network" alone leaves it ambiguous whether it describes what will
    // happen or what already has. On, they name the resulting state.
    await showState(healthyState({ configured: true, hidden: false, active: false }))
    const offLabels = [...panel.element.querySelectorAll('label')].map((label) =>
      (label.textContent ?? '').trim(),
    )

    await showState(healthyState({ configured: true, hidden: true, active: true }))
    const onLabels = [...panel.element.querySelectorAll('label')].map((label) =>
      (label.textContent ?? '').trim(),
    )

    expect(offLabels).toContain('Hide network')
    expect(offLabels).toContain('Enable hotspot')
    expect(onLabels).toContain('Network is hidden')
    expect(onLabels).toContain('Hotspot enabled')
  })

  it('puts both toggles in the header, outside the form', async () => {
    // They are the two controls worth reading at a glance; buried among the
    // fields they were easy to miss, and one sat below a scroll.
    await showState(healthyState({ configured: true }))

    const form = panel.element.querySelector('form')
    const hideToggle = [...panel.element.querySelectorAll('label')].find((label) =>
      /Hide network|Network is hidden/.test(label.textContent ?? ''),
    )

    expect(hideToggle, 'the hide toggle must render').toBeDefined()
    expect(form?.contains(hideToggle!)).toBe(false)
  })

  it('places the save action after the DHCP lease list', async () => {
    await showState(healthyState({ configured: true }))

    const saveButton = [...panel.element.querySelectorAll('button')].find((button) =>
      /Save hotspot settings/i.test(button.textContent ?? ''),
    )
    const leasesSummary = [...panel.element.querySelectorAll('summary')].find((summary) =>
      /Recent DHCP leases/i.test(summary.textContent ?? ''),
    )

    expect(saveButton).toBeDefined()
    expect(leasesSummary).toBeDefined()
    expect(
      leasesSummary!.compareDocumentPosition(saveButton!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('keeps the save button wired to the form it sits outside of', async () => {
    // A submit button outside its form is inert unless it names one. Without
    // this the button would render perfectly and simply do nothing.
    await showState(healthyState({ configured: true }))

    const form = panel.element.querySelector('form')
    const saveButton = [...panel.element.querySelectorAll('button')].find((button) =>
      /Save hotspot settings/i.test(button.textContent ?? ''),
    )

    expect(form?.id).toBeTruthy()
    expect(form?.contains(saveButton!)).toBe(false)
    expect(saveButton?.getAttribute('form')).toBe(form?.id)
  })
})
