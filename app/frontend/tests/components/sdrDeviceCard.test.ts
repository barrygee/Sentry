import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient, type DeviceStatus } from '../../src/api/client.js'
import type { Component } from '../../src/core/component.js'
import { sdrDeviceCard } from '../../src/components/device/sdrDeviceCard.js'
import { applySnapshot, sdrsStore } from '../../src/state/sdrsStore.js'

/**
 * Tests that an inline edit survives a background refresh.
 *
 * The card re-synced every draft from the server whenever the store changed,
 * guarded only by "is there a pending optimistic patch". A patch exists only
 * *after* a field commits on blur — so from the first keystroke until the
 * operator tabbed away there was nothing pending, and `health` arrives every
 * five seconds. Each one reset the drafts, wiped the inputs, and left a later
 * blur committing the empty draft it had just been handed.
 *
 * Reported as "adding a note gets lost". Name, port and antenna were going the
 * same way, silently.
 */

function deviceFixture(overrides: Partial<DeviceStatus> = {}): DeviceStatus {
  return {
    device_id: 'serial:AIS-01',
    record_id: 1,
    identity_kind: 'serial',
    identity_key: 'AIS-01',
    needs_identification: false,
    name: 'AIS SDR',
    description: '',
    notes: '',
    antenna: '',
    visibility: 'public',
    state: 'streaming',
    state_since: 0,
    state_reason: null,
    present: true,
    enabled: true,
    usb: null,
    output: { host: '192.168.1.45', iq_port: 1234, control_port: 1236 },
    tuner: null,
    processes: null,
    clients: null,
    last_seen_at: 0,
    ...overrides,
  } as DeviceStatus
}

/**
 * A background refresh, as the operator experiences it.
 *
 * The card does not subscribe to the store — `sdrsView`'s `keyedList` re-renders
 * it by calling `update`, once per store change. Driving only the store would
 * never reach the card and would test nothing.
 */
async function backgroundRefresh(device: DeviceStatus): Promise<void> {
  applySnapshot({ generated_at: Date.now(), sdrs: [device] })
  card.update({ device, onRequestSerialFlash: () => {} })
  await Promise.resolve()
}

let card: Component<{ device: DeviceStatus; onRequestSerialFlash: (id: string) => void }>

/**
 * The card's Save/Discard controls, which exist only while something is unsaved.
 *
 * Walks the inline `display` that `setVisible` sets, rather than `offsetParent`:
 * jsdom does no layout, so `offsetParent` is always null and would report every
 * button as hidden.
 */
function isVisible(element: HTMLElement): boolean {
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    if (node.style.display === 'none') return false
  }
  return true
}

function findButton(label: string): HTMLButtonElement | undefined {
  const buttons = Array.from(card.element.querySelectorAll('button'))
  return buttons.find((button) => (button.textContent ?? '').trim() === label && isVisible(button))
}

function buttonLabelled(label: string): HTMLButtonElement {
  const button = findButton(label)
  if (!button) throw new Error(`No visible button labelled "${label}"`)
  return button
}

function fieldByLabel(label: string): HTMLTextAreaElement | HTMLInputElement {
  const controls = Array.from(card.element.querySelectorAll('input, textarea'))
  const match = controls.find((control) => {
    const id = control.getAttribute('id')
    if (!id) return false
    const associated = card.element.querySelector(`label[for="${id}"]`)
    return (associated?.textContent ?? '').trim().toLowerCase() === label.toLowerCase()
  })
  if (!match) throw new Error(`No field labelled "${label}"`)
  return match as HTMLTextAreaElement | HTMLInputElement
}

beforeEach(() => {
  // Stubbed because these assert the *optimistic* patch the store records, not
  // the request. Left real, it reaches `fetch` with a relative URL, which has
  // no base in Node and throws — passing locally under jsdom and failing in CI.
  vi.spyOn(apiClient, 'patchDevice').mockResolvedValue(undefined as never)

  // The store is a module-level singleton, so a pending patch left by an
  // earlier test would keep the next card from ever re-syncing.
  sdrsStore.setState({ pendingPatchesByDeviceId: {} })

  document.body.innerHTML = `
    <div id="live-region-polite"></div>
    <div id="live-region-assertive"></div>
  `
  const device = deviceFixture()
  applySnapshot({ generated_at: 0, sdrs: [device] })
  card = sdrDeviceCard({ device, onRequestSerialFlash: () => {} })
  document.body.appendChild(card.element)
})

afterEach(() => {
  vi.restoreAllMocks()
  card.destroy()
  document.body.innerHTML = ''
})

describe('sdrDeviceCard inline edits', () => {
  it('keeps a note being typed when a background refresh arrives', async () => {
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Feeder cable due for replacement'
    notes.dispatchEvent(new Event('input', { bubbles: true }))

    await backgroundRefresh(deviceFixture())

    // The five-second `health` heartbeat used to empty this.
    expect(notes.value).toBe('Feeder cable due for replacement')
  })

  it('keeps a name being typed', async () => {
    const name = fieldByLabel('Name')
    name.focus()
    name.value = 'Roof AIS'
    name.dispatchEvent(new Event('input', { bubbles: true }))

    await backgroundRefresh(deviceFixture())

    expect(name.value).toBe('Roof AIS')
  })

  it('does not save on blur', async () => {
    // The change the operator asked for: leaving a field is not a decision to
    // persist it. Blur still *validates* and cleans the value up — it just no
    // longer writes it.
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Intermittent below 150 MHz'
    notes.dispatchEvent(new Event('input', { bubbles: true }))
    notes.blur()
    await Promise.resolve()

    expect(sdrsStore.state.pendingPatchesByDeviceId['serial:AIS-01']).toBeUndefined()
    expect(apiClient.patchDevice).not.toHaveBeenCalled()
  })

  it('saves what was typed when Save is pressed', async () => {
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Swapped the feeder'
    notes.dispatchEvent(new Event('input', { bubbles: true }))
    notes.blur()

    // A refresh between typing and saving must not undo the edit — this is the
    // window the old focus-based guard left open, since nothing is focused once
    // the operator has tabbed away and reached for the button.
    await backgroundRefresh(deviceFixture())
    buttonLabelled('Save changes').click()
    await Promise.resolve()

    expect(sdrsStore.state.pendingPatchesByDeviceId['serial:AIS-01']?.notes).toBe(
      'Swapped the feeder',
    )
  })

  it('sends only the fields that changed', async () => {
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Roof work booked'
    notes.dispatchEvent(new Event('input', { bubbles: true }))
    notes.blur()
    buttonLabelled('Save changes').click()
    await Promise.resolve()

    // Untouched fields are absent, not resent — a save of the whole row would
    // clobber whatever another browser changed while this card sat open.
    const patch = sdrsStore.state.pendingPatchesByDeviceId['serial:AIS-01']
    expect(Object.keys(patch ?? {})).toEqual(['notes'])
  })

  it('throws the edit away on Discard, and saves nothing', async () => {
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Typed by mistake'
    notes.dispatchEvent(new Event('input', { bubbles: true }))
    notes.blur()

    buttonLabelled('Discard').click()
    await Promise.resolve()

    expect(fieldByLabel('Notes').value).toBe('')
    expect(apiClient.patchDevice).not.toHaveBeenCalled()
  })

  it('offers no Save on a card with nothing unsaved', () => {
    // A card at rest carries no controls that would do nothing.
    expect(findButton('Save changes')).toBeUndefined()
  })

  it('still follows the server for a card nobody is editing', async () => {
    // The guard must not freeze an idle card: a rename from Sentinel, or from
    // another browser, still has to land.
    await backgroundRefresh(deviceFixture({ name: 'Renamed elsewhere' }))

    expect(fieldByLabel('Name').value).toBe('Renamed elsewhere')
  })

  it('collapses from its header, keeping status and the switches visible', () => {
    const details = card.element.querySelector('details')
    const summary = details?.querySelector('summary')

    expect(details).not.toBeNull()
    // Closed by default — a rack of cards opens as a scannable list, and the
    // operator's own choices are remembered from there.
    expect(details?.open).toBe(false)
    // Everything that must survive collapsing lives in the summary.
    expect(summary?.querySelector('input[type="checkbox"]')).not.toBeNull()
  })

  it('does not collapse when a switch inside the header is clicked', () => {
    // A click inside a `<summary>` reaches the summary and fires its default,
    // so without the guard, turning an SDR off would fold the card shut
    // underneath the finger that did it.
    const details = card.element.querySelector('details')
    // Open it first: the guard is about a click on a switch not *changing* the
    // disclosure, which is only observable from a known starting state.
    details!.open = true
    const toggle = details
      ?.querySelector('summary')
      ?.querySelector('input[type="checkbox"]') as HTMLInputElement | null

    expect(toggle).not.toBeNull()
    toggle!.click()

    expect(details?.open).toBe(true)
  })

  it('shows the dialable address on the switch row, collapsed only', () => {
    // The one value an operator has to type into Sentinel on another machine.
    // Expanded, "Host IP" and "Output port" carry the same two halves in full,
    // so the summary line hands it over rather than repeating it.
    //
    // The collapsed/expanded split is `group-open:hidden`, which is Tailwind —
    // jsdom applies no stylesheet, so toggling `details.open` here would not
    // change what `querySelector` sees. The class is therefore the assertion,
    // not the rendered visibility; that part is checked in a browser.
    const details = card.element.querySelector('details')
    const summary = details?.querySelector('summary')
    const addressOf = () =>
      [...(summary?.querySelectorAll('span') ?? [])].find((span) =>
        /^\d+\.\d+\.\d+\.\d+:\d+$/.test((span.textContent ?? '').trim()),
      )

    const address = addressOf()
    expect(address?.textContent?.trim()).toBe('192.168.1.45:1234')
    expect(address?.className).toContain('group-open:hidden')
    // Matches `BaseToggle`'s caption ink, so it reads as a peer of the switch
    // labels beside it rather than a dimmer annotation.
    expect(address?.className).toContain('text-ink-primary')
    expect(address?.className).not.toContain('text-signal-muted')
  })

  it('states the host on its own field once expanded', () => {
    // The half of the address the collapsed line gives up on opening. Read-only
    // — it is whatever host the page was loaded over, not a device setting.
    const labels = [...card.element.querySelectorAll('span, dt')]
    const hostLabel = labels.find((node) => (node.textContent ?? '').trim() === 'Host IP')
    expect(hostLabel).toBeDefined()

    const hostCell = hostLabel?.parentElement
    expect(hostCell?.textContent).toContain('192.168.1.45')
    expect(hostCell?.textContent).not.toContain('1234')
  })
})
