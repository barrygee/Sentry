import { axe } from 'jest-axe'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { DeviceStatus } from '../../src/api/client.js'
import type { Component } from '../../src/core/component.js'
import { noticeList } from '../../src/components/sdrs/noticeList.js'
import { applyNotice, applySnapshot, sdrsStore } from '../../src/state/sdrsStore.js'
import type { NoticeEvent } from '../../src/types/sdrs.js'

/**
 * Tests for the rendered notice log — the device attribution and repeat count
 * an operator actually reads, and the accessible names a screen-reader user
 * hears in their place.
 */

const CRASH_LOOP_MESSAGE =
  'restart budget exhausted (5 restarts within 120s); retrying with capped backoff'

function crashLoopNotice(deviceId: string | null, ts = 1000): NoticeEvent {
  return {
    level: 'error',
    code: 'crash_loop',
    message: CRASH_LOOP_MESSAGE,
    device_id: deviceId,
    ts,
  }
}

function deviceNamed(deviceId: string, name: string): DeviceStatus {
  return { device_id: deviceId, name } as DeviceStatus
}

/** The store coalesces notifications to a microtask, so the DOM lags a tick behind `setState`. */
async function flushStore(): Promise<void> {
  await Promise.resolve()
}

let container: HTMLElement
let list: Component<void>

function rowTexts(): string[] {
  return Array.from(list.element.querySelectorAll('li p')).map((paragraph) =>
    (paragraph.textContent ?? '').replace(/\s+/g, ' ').trim(),
  )
}

function dismissButtonNames(): string[] {
  return Array.from(list.element.querySelectorAll('li button'))
    .map((button) => button.getAttribute('aria-label') ?? '')
    .filter((name) => name.startsWith('Dismiss notice'))
}

beforeEach(() => {
  // `liveAnnouncer` (reached through the dismiss control) requires these to exist.
  document.body.innerHTML = `
    <div id="live-region-polite"></div>
    <div id="live-region-assertive"></div>
  `
  sdrsStore.setState({ notices: [], devicesById: {}, order: [] })

  container = document.createElement('div')
  document.body.appendChild(container)
  list = noticeList()
  container.appendChild(list.element)
})

afterEach(() => {
  list.destroy()
  container.remove()
})

describe('noticeList', () => {
  it('hides the list entirely when there is nothing to show', () => {
    expect(list.element.style.display).toBe('none')
  })

  it('shows the list once a notice arrives', async () => {
    applyNotice(crashLoopNotice(null))
    await flushStore()

    expect(list.element.style.display).toBe('')
    expect(rowTexts()).toEqual([CRASH_LOOP_MESSAGE])
  })

  it('prefixes a device notice with that device name', async () => {
    applySnapshot({ generated_at: 1, sdrs: [deviceNamed('usb:1-2.1', 'RTL-SDR-V4')] })
    applyNotice(crashLoopNotice('usb:1-2.1'))
    await flushStore()

    expect(rowTexts()).toEqual([`RTL-SDR-V4 — ${CRASH_LOOP_MESSAGE}`])
  })

  it('falls back to the device id when the device has no name', async () => {
    applyNotice(crashLoopNotice('usb:1-9.9'))
    await flushStore()

    expect(rowTexts()).toEqual([`usb:1-9.9 — ${CRASH_LOOP_MESSAGE}`])
  })

  it('leaves an SDR-wide notice unprefixed, with no stray separator', async () => {
    applyNotice(crashLoopNotice(null))
    await flushStore()

    expect(rowTexts()[0]?.startsWith('—')).toBe(false)
    expect(rowTexts()).toEqual([CRASH_LOOP_MESSAGE])
  })

  it('distinguishes the same message from two devices — the reported defect', async () => {
    applySnapshot({
      generated_at: 1,
      sdrs: [deviceNamed('usb:1-2.1', 'RTL-SDR-V4'), deviceNamed('usb:1-3.1', 'NESDR-SMART')],
    })
    applyNotice(crashLoopNotice('usb:1-2.1'))
    applyNotice(crashLoopNotice('usb:1-3.1'))
    await flushStore()

    const texts = rowTexts()
    expect(texts).toHaveLength(2)
    expect(new Set(texts).size).toBe(2)
    expect(texts).toContain(`RTL-SDR-V4 — ${CRASH_LOOP_MESSAGE}`)
    expect(texts).toContain(`NESDR-SMART — ${CRASH_LOOP_MESSAGE}`)
  })

  it('relabels an outstanding notice when its device is renamed', async () => {
    applySnapshot({ generated_at: 1, sdrs: [deviceNamed('usb:1-2.1', 'RTL-SDR-V4')] })
    applyNotice(crashLoopNotice('usb:1-2.1'))
    await flushStore()

    applySnapshot({ generated_at: 2, sdrs: [deviceNamed('usb:1-2.1', 'Roof ADSB')] })
    await flushStore()

    expect(rowTexts()).toEqual([`Roof ADSB — ${CRASH_LOOP_MESSAGE}`])
  })

  it('shows no count for a notice seen once', async () => {
    applyNotice(crashLoopNotice(null))
    await flushStore()

    expect(rowTexts()[0]).not.toContain('×')
  })

  it('shows a count once the notice repeats', async () => {
    applyNotice(crashLoopNotice(null, 1000))
    applyNotice(crashLoopNotice(null, 2000))
    applyNotice(crashLoopNotice(null, 3000))
    await flushStore()

    // No space in the text: the gap before the count is a left margin, so the
    // count reads as its own element rather than as part of the sentence.
    expect(rowTexts()).toEqual([`${CRASH_LOOP_MESSAGE}×3`])
  })

  it('hides the count glyph from assistive tech, which spells it out instead', async () => {
    applyNotice(crashLoopNotice(null, 1000))
    applyNotice(crashLoopNotice(null, 2000))
    await flushStore()

    const countElement = list.element.querySelector('li p span[aria-hidden="true"]')
    expect(countElement?.textContent).toBe('×2')
  })

  it('names the device and repeat count on the dismiss control', async () => {
    applySnapshot({ generated_at: 1, sdrs: [deviceNamed('usb:1-2.1', 'RTL-SDR-V4')] })
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-2.1', 2000))
    await flushStore()

    expect(dismissButtonNames()).toEqual([
      `Dismiss notice for RTL-SDR-V4: ${CRASH_LOOP_MESSAGE} (repeated 2 times)`,
    ])
  })

  it('omits the device from the dismiss control for an SDR-wide notice', async () => {
    applyNotice(crashLoopNotice(null))
    await flushStore()

    expect(dismissButtonNames()).toEqual([`Dismiss notice: ${CRASH_LOOP_MESSAGE}`])
  })

  it('gives error notices an assertive role and info notices a polite one', async () => {
    applyNotice(crashLoopNotice(null))
    applyNotice({ ...crashLoopNotice(null), level: 'info', code: 'looped', message: 'Looped.' })
    await flushStore()

    const roles = Array.from(list.element.querySelectorAll('li > div')).map((box) =>
      box.getAttribute('role'),
    )
    expect(roles).toContain('alert')
    expect(roles).toContain('status')
  })

  it('tones each level distinctly, warn included', async () => {
    applyNotice({ ...crashLoopNotice(null), level: 'error', message: 'An error.' })
    applyNotice({ ...crashLoopNotice(null), level: 'warn', code: 'port', message: 'A warning.' })
    applyNotice({ ...crashLoopNotice(null), level: 'info', code: 'looped', message: 'A note.' })
    await flushStore()

    const toneClasses = Array.from(list.element.querySelectorAll('li > div')).map(
      (box) => box.className,
    )
    expect(toneClasses.some((className) => className.includes('bg-signal-danger'))).toBe(true)
    expect(toneClasses.some((className) => className.includes('bg-signal-warn-fill'))).toBe(true)
    expect(toneClasses.some((className) => className.includes('bg-signal-info'))).toBe(true)
  })

  it('ignores an external update() call — the list is store-driven', async () => {
    applyNotice(crashLoopNotice(null))
    await flushStore()

    list.update()

    expect(rowTexts()).toEqual([CRASH_LOOP_MESSAGE])
  })

  it('drops a dismissed notice from the rendered list', async () => {
    applyNotice(crashLoopNotice(null))
    await flushStore()
    const dismissButton = list.element.querySelector('li button') as HTMLButtonElement

    dismissButton.click() // arms
    const confirmButton = Array.from(list.element.querySelectorAll('li button')).find(
      (button) => button.getAttribute('aria-label') === 'Confirm dismiss notice',
    ) as HTMLButtonElement
    confirmButton.click()
    await flushStore()

    expect(rowTexts()).toEqual([])
    expect(list.element.style.display).toBe('none')
  })

  it('has no detectable accessibility violations', async () => {
    applySnapshot({ generated_at: 1, sdrs: [deviceNamed('usb:1-2.1', 'RTL-SDR-V4')] })
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-2.1', 2000))
    applyNotice(crashLoopNotice(null, 3000))
    await flushStore()

    expect(await axe(container)).toHaveNoViolations()
  })
})
