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

  it('commits what was typed, not what the refresh overwrote it with', async () => {
    // The nastier half: even where the DOM survived, the card's draft had been
    // reset, so blurring committed an empty value over the operator's text.
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Intermittent below 150 MHz'
    notes.dispatchEvent(new Event('input', { bubbles: true }))

    await backgroundRefresh(deviceFixture())
    notes.dispatchEvent(new Event('blur', { bubbles: false }))
    await Promise.resolve()

    const pending = sdrsStore.state.pendingPatchesByDeviceId['serial:AIS-01']
    expect(pending?.notes).toBe('Intermittent below 150 MHz')
  })

  it('commits a note typed and blurred with no refresh in between', async () => {
    // The commonest case, and the one the other tests miss: each of those has a
    // background refresh between typing and blurring, which is itself what
    // brings the field's props up to date. Type and click straight away and
    // there is no refresh — the field would otherwise commit the value it was
    // last rendered with, which is whatever was there before.
    const notes = fieldByLabel('Notes')
    notes.focus()
    notes.value = 'Swapped the feeder'
    notes.dispatchEvent(new Event('input', { bubbles: true }))

    notes.dispatchEvent(new Event('blur', { bubbles: false }))
    await Promise.resolve()

    expect(sdrsStore.state.pendingPatchesByDeviceId['serial:AIS-01']?.notes).toBe(
      'Swapped the feeder',
    )
  })

  it('still follows the server for a card nobody is editing', async () => {
    // The guard must not freeze an idle card: a rename from Sentinel, or from
    // another browser, still has to land.
    await backgroundRefresh(deviceFixture({ name: 'Renamed elsewhere' }))

    expect(fieldByLabel('Name').value).toBe('Renamed elsewhere')
  })
})
