import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { WiredShareState } from '../../src/api/client.js'
import type { Component } from '../../src/core/component.js'
import { wiredPanel } from '../../src/components/wired/wiredPanel.js'
import { wiredStore, type WiredPhase } from '../../src/state/wiredStore.js'

/**
 * Tests for the wired-sharing settings section.
 *
 * The obligation is the same one the hotspot panel carries: whatever the state,
 * it must say something useful rather than render empty — an operator who
 * cannot use the feature needs to be told why, in a place that points at the
 * fix.
 *
 * Two things here are specific to the cable and are worth pinning, because both
 * are the difference between "this is broken" and "this is fine, plug it in":
 *
 * - The blocked-control message points at the **hotspot's** switch, since the
 *   two features share it (ADR-0014). Pointing at a wired switch that does not
 *   exist would send an operator looking for a control they will never find.
 * - `no_carrier` is surfaced prominently. Sharing running with nothing plugged
 *   in is by far the commonest reason a correct configuration appears to do
 *   nothing at all.
 */

function healthyState(overrides: Partial<WiredShareState> = {}): WiredShareState {
  return {
    control_enabled: true,
    console_password_set: true,
    available: true,
    configured: false,
    enabled: false,
    active: false,
    pending_confirmation: false,
    carrier_up: true,
    uplink_interface_is_share_interface: false,
    warnings: [],
    ...overrides,
  } as WiredShareState
}

async function showState(state: WiredShareState | null, phase: WiredPhase = 'form'): Promise<void> {
  wiredStore.setState({ state, phase, interfaces: [], clients: null })
  await Promise.resolve()
}

let panel: Component<void>

/**
 * The panel's text as an operator can actually read it.
 *
 * Deliberately not `textContent`. The panel keeps every notice mounted and
 * toggles `display: none` on it (`setVisible`), so `textContent` returns the
 * copy for *every* state at once — including the notices this render decided to
 * hide. An assertion against that proves nothing in either direction: "contains"
 * passes on invisible text, and "does not contain" can never pass at all.
 */
function panelText(): string {
  const parts: string[] = []
  const walk = (node: Node): void => {
    if (node instanceof HTMLElement && node.style.display === 'none') return
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(node.textContent ?? '')
      return
    }
    node.childNodes.forEach(walk)
  }
  walk(panel.element)
  return parts.join(' ').replace(/\s+/g, ' ').trim()
}

beforeEach(() => {
  document.body.innerHTML = `
    <div id="live-region-polite"></div>
    <div id="live-region-assertive"></div>
  `
  wiredStore.setState({
    state: null,
    interfaces: [],
    clients: null,
    phase: 'loading',
    errorMessage: null,
    errorCode: null,
    errorCommandOutput: null,
  })
  panel = wiredPanel()
  document.body.appendChild(panel.element)
})

afterEach(() => {
  panel.destroy()
  document.body.innerHTML = ''
})

describe('wiredPanel', () => {
  it('is a labelled section, matching the hotspot panel it sits beneath', () => {
    expect(panel.element.tagName).toBe('SECTION')
    expect(panel.element.getAttribute('role')).toBeNull()
    expect(panel.element.getAttribute('aria-labelledby')).toBeTruthy()
  })

  it('names the feature in a way that says which cable it means', () => {
    expect(panelText()).toContain('Wired (Ethernet) sharing')
  })

  it('says it is loading before any state arrives', () => {
    expect(panelText()).toContain('Loading wired-sharing settings')
  })

  it.each([
    ['host network control is switched off', { control_enabled: false }, 'hotspot'],
    ['no controller password is set', { console_password_set: false }, 'controller password'],
    ['NetworkManager is unreachable', { available: false }, 'NetworkManager'],
  ])('explains the blockage when %s', async (_label, overrides, expected) => {
    await showState(healthyState(overrides))

    expect(panelText()).toContain(expected)
  })

  it('points at the hotspot box for the shared control switch', async () => {
    // The switch is literally the hotspot's (ADR-0014). Sending an operator to
    // look for a wired one would be sending them to something that is not there.
    await showState(healthyState({ control_enabled: false }))

    expect(panelText()).toContain('Turn it on in the WiFi hotspot box above')
  })

  it('reports the control blockage before the password one', async () => {
    // Both wrong means naming the first thing to fix, matching the API's own
    // ordering — otherwise the panel and the error disagree about what to do.
    await showState(healthyState({ control_enabled: false, console_password_set: false }))

    expect(panelText()).toContain('Host network control is switched off')
  })

  it('shows the form once nothing is blocking it', async () => {
    await showState(healthyState())

    expect(panel.element.querySelector('form')).not.toBeNull()
  })

  it('hides the form while something is blocking it', async () => {
    // Rendering a form whose every submission would be refused invites an
    // operator to fill it in and be told no.
    await showState(healthyState({ control_enabled: false }))

    const form = panel.element.querySelector('form')
    expect(form === null || form.closest('[hidden]') !== null).toBe(true)
  })

  it('explains an empty client list caused by an unplugged cable', async () => {
    // The single most useful thing this panel can say.
    await showState(healthyState({ active: true, carrier_up: false, warnings: ['no_carrier'] }))

    expect(panelText()).toContain('nothing is plugged into that port')
  })

  it('stays quiet about the cable when the host did not report one', async () => {
    // `carrier_up: null` is "cannot tell", which must not read as "unplugged".
    await showState(healthyState({ active: true, carrier_up: null }))

    expect(panelText()).not.toContain('nothing is plugged into that port')
  })

  it('warns when the published host is not the address a cabled machine gets', async () => {
    await showState(
      healthyState({ configured: true, warnings: ['advertised_host_overrides_gateway'] }),
    )

    expect(panelText()).toContain('SENTRY_ADVERTISED_HOST')
  })

  it('shows the address a cabled machine should be given, once sharing is up', async () => {
    await showState(healthyState({ configured: true, active: true, gateway_address: '10.10.10.1' }))

    expect(panelText()).toContain('10.10.10.1')
  })

  it('does not advertise an address while sharing is stopped', async () => {
    // Nothing would answer on it, so printing it is an invitation to a dead end.
    await showState(
      healthyState({ configured: true, active: false, gateway_address: '10.10.10.1' }),
    )

    expect(panelText()).not.toContain('10.10.10.1')
  })

  it('renders the failure message when a request fails', async () => {
    wiredStore.setState({
      state: healthyState(),
      phase: 'failed',
      errorMessage: 'Could not start wired sharing.',
      errorCode: 'wired_command_failed',
      errorCommandOutput: null,
      interfaces: [],
      clients: null,
    })
    await Promise.resolve()

    expect(panelText()).toContain('Could not start wired sharing.')
  })

  it('prints the failing command output verbatim when the server sent one', async () => {
    // The only thing that says *why* NetworkManager refused. A paraphrase of an
    // nmcli error is a guess, so it is shown as-is.
    wiredStore.setState({
      state: healthyState(),
      phase: 'failed',
      errorMessage: 'Could not start wired sharing.',
      errorCode: 'wired_command_failed',
      errorCommandOutput: 'Error: Connection activation failed: No suitable device found',
      interfaces: [],
      clients: null,
    })
    await Promise.resolve()

    expect(panel.element.querySelector('pre')?.textContent).toContain('No suitable device found')
  })

  it('announces progress on a live region rather than only visually', async () => {
    await showState(healthyState(), 'submitting')

    const statusRegion = panel.element.querySelector('[role="status"].sr-only')
    expect(statusRegion?.textContent).toContain('Applying wired-sharing settings')
  })

  it('announces a failure assertively', async () => {
    wiredStore.setState({
      state: healthyState(),
      phase: 'failed',
      errorMessage: 'Could not start wired sharing.',
      errorCode: 'wired_command_failed',
      errorCommandOutput: null,
      interfaces: [],
      clients: null,
    })
    await Promise.resolve()

    const alertRegion = panel.element.querySelector('[role="alert"].sr-only')
    expect(alertRegion?.textContent).toContain('Could not start wired sharing.')
  })

  it('shows the lease list only once a share has been configured', async () => {
    await showState(healthyState({ configured: false }))
    const beforeConfiguring = panelText()

    await showState(healthyState({ configured: true }))

    expect(beforeConfiguring).not.toContain('Recent DHCP leases')
    expect(panelText()).toContain('Recent DHCP leases')
  })

  it('shows the confirmation countdown while a change is on trial', async () => {
    await showState(
      healthyState({
        configured: true,
        active: true,
        interface: 'eth0',
        pending_confirmation: true,
        confirm_deadline_ms: Date.now() + 90_000,
      }),
      'awaiting-confirm',
    )

    expect(panelText()).toContain('unless you confirm')
    expect(panelText()).toContain('eth0')
  })

  it('survives being destroyed and leaves no timer behind', async () => {
    // The countdown owns a one-second interval; a leaked one would keep
    // announcing after the panel that hosted it is gone.
    await showState(
      healthyState({
        configured: true,
        active: true,
        pending_confirmation: true,
        confirm_deadline_ms: Date.now() + 90_000,
      }),
      'awaiting-confirm',
    )

    expect(() => {
      panel.destroy()
    }).not.toThrow()

    // Re-created so `afterEach`'s destroy has something valid to act on.
    panel = wiredPanel()
  })
})
