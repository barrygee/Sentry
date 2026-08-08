import { beforeEach, describe, expect, it } from 'vitest'

import type { DeviceStatus } from '../../src/api/client.js'
import {
  applyNotice,
  applySnapshot,
  deviceLabel,
  dismissNotice,
  sdrsStore,
} from '../../src/state/sdrsStore.js'
import type { NoticeEvent } from '../../src/types/sdrs.js'

/**
 * Tests for the notice log: `applyNotice`'s repeat coalescing, `dismissNotice`,
 * and the shared `deviceLabel` fallback.
 *
 * The store is a module-level singleton, so every test resets it explicitly
 * rather than relying on import order.
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

/** A `DeviceStatus` with only the fields the notice log reads; the rest are irrelevant here. */
function deviceNamed(deviceId: string, name: string): DeviceStatus {
  return { device_id: deviceId, name } as DeviceStatus
}

function resetStore(): void {
  sdrsStore.setState({ notices: [], devicesById: {}, order: [] })
}

beforeEach(() => {
  resetStore()
})

describe('applyNotice', () => {
  it('records a first notice with a repeat count of one', () => {
    applyNotice(crashLoopNotice('usb:1-2.1'))

    expect(sdrsStore.state.notices).toHaveLength(1)
    expect(sdrsStore.state.notices[0]).toMatchObject({
      code: 'crash_loop',
      device_id: 'usb:1-2.1',
      dismissed: false,
      repeatCount: 1,
      ts: 1000,
      lastSeenTs: 1000,
    })
  })

  it('gives each notice a distinct id even when two arrive in the same millisecond', () => {
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-3.1', 1000))

    const [first, second] = sdrsStore.state.notices
    expect(first?.id).not.toBe(second?.id)
  })

  it('coalesces an identical repeat into the existing row instead of adding one', () => {
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-2.1', 2000))
    applyNotice(crashLoopNotice('usb:1-2.1', 3000))

    expect(sdrsStore.state.notices).toHaveLength(1)
    expect(sdrsStore.state.notices[0]).toMatchObject({ repeatCount: 3 })
  })

  it('advances lastSeenTs to the newest occurrence but leaves ts at the first', () => {
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-2.1', 5000))

    expect(sdrsStore.state.notices[0]).toMatchObject({ ts: 1000, lastSeenTs: 5000 })
  })

  it('keeps a coalescing notice in place rather than promoting it to the top', () => {
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-3.1', 2000))
    applyNotice(crashLoopNotice('usb:1-2.1', 3000))

    // Newest-first: the second device leads, and the repeat did not reorder them.
    expect(sdrsStore.state.notices.map((notice) => notice.device_id)).toEqual([
      'usb:1-3.1',
      'usb:1-2.1',
    ])
    expect(sdrsStore.state.notices[1]).toMatchObject({ repeatCount: 2 })
  })

  it('keeps the same message from two different devices as two rows', () => {
    applyNotice(crashLoopNotice('usb:1-2.1'))
    applyNotice(crashLoopNotice('usb:1-3.1'))

    expect(sdrsStore.state.notices).toHaveLength(2)
    expect(sdrsStore.state.notices.every((notice) => notice.repeatCount === 1)).toBe(true)
  })

  it('treats an SDR-wide notice and a device notice as different rows', () => {
    applyNotice(crashLoopNotice(null))
    applyNotice(crashLoopNotice('usb:1-2.1'))

    expect(sdrsStore.state.notices).toHaveLength(2)
  })

  it('coalesces repeats of an SDR-wide notice, matching on a null device', () => {
    applyNotice(crashLoopNotice(null, 1000))
    applyNotice(crashLoopNotice(null, 2000))

    expect(sdrsStore.state.notices).toHaveLength(1)
    expect(sdrsStore.state.notices[0]).toMatchObject({ repeatCount: 2 })
  })

  it('does not coalesce when the code differs', () => {
    applyNotice(crashLoopNotice('usb:1-2.1'))
    applyNotice({ ...crashLoopNotice('usb:1-2.1'), code: 'spawn_failed' })

    expect(sdrsStore.state.notices).toHaveLength(2)
  })

  it('does not coalesce when the message differs', () => {
    applyNotice(crashLoopNotice('usb:1-2.1'))
    applyNotice({ ...crashLoopNotice('usb:1-2.1'), message: 'port 1234 is already in use' })

    expect(sdrsStore.state.notices).toHaveLength(2)
  })

  it('starts a fresh row when the condition recurs after being dismissed', () => {
    applyNotice(crashLoopNotice('usb:1-2.1', 1000))
    applyNotice(crashLoopNotice('usb:1-2.1', 2000))
    const dismissedId = sdrsStore.state.notices[0]?.id
    expect(dismissedId).toBeDefined()
    dismissNotice(dismissedId as string)

    applyNotice(crashLoopNotice('usb:1-2.1', 3000))

    expect(sdrsStore.state.notices).toHaveLength(2)
    // The dismissed row keeps its count and stays dismissed; the recurrence is new.
    expect(sdrsStore.state.notices[0]).toMatchObject({ dismissed: false, repeatCount: 1 })
    expect(sdrsStore.state.notices[1]).toMatchObject({ dismissed: true, repeatCount: 2 })
  })

  it('caps the log at 50, dropping the oldest', () => {
    for (let index = 0; index < 55; index += 1) {
      applyNotice({ ...crashLoopNotice(`usb:1-${index}`), message: `failure ${index}` })
    }

    expect(sdrsStore.state.notices).toHaveLength(50)
    expect(sdrsStore.state.notices[0]?.message).toBe('failure 54')
    expect(sdrsStore.state.notices[49]?.message).toBe('failure 5')
  })

  it('does not consume a log slot for a repeat, so unrelated notices survive a flap', () => {
    applyNotice({ ...crashLoopNotice('usb:1-9.9'), message: 'the one that matters' })
    for (let index = 0; index < 100; index += 1) {
      applyNotice(crashLoopNotice('usb:1-2.1', 1000 + index))
    }

    expect(sdrsStore.state.notices).toHaveLength(2)
    expect(
      sdrsStore.state.notices.some((notice) => notice.message === 'the one that matters'),
    ).toBe(true)
  })
})

describe('dismissNotice', () => {
  it('marks only the matching notice dismissed', () => {
    applyNotice(crashLoopNotice('usb:1-2.1'))
    applyNotice(crashLoopNotice('usb:1-3.1'))
    const targetId = sdrsStore.state.notices[0]?.id

    dismissNotice(targetId as string)

    expect(sdrsStore.state.notices[0]?.dismissed).toBe(true)
    expect(sdrsStore.state.notices[1]?.dismissed).toBe(false)
  })

  it('leaves the log untouched when the id matches nothing', () => {
    applyNotice(crashLoopNotice('usb:1-2.1'))

    dismissNotice('no-such-id')

    expect(sdrsStore.state.notices[0]?.dismissed).toBe(false)
  })
})

describe('deviceLabel', () => {
  it('uses the device name when it has one', () => {
    applySnapshot({
      generated_at: 1,
      sdrs: [deviceNamed('usb:1-2.1', 'RTL-SDR-V4')],
    })

    expect(deviceLabel(sdrsStore.state, 'usb:1-2.1')).toBe('RTL-SDR-V4')
  })

  it('falls back to the device id when the name is empty', () => {
    applySnapshot({ generated_at: 1, sdrs: [deviceNamed('usb:1-2.1', '')] })

    expect(deviceLabel(sdrsStore.state, 'usb:1-2.1')).toBe('usb:1-2.1')
  })

  it('falls back to the device id when the device is unknown', () => {
    expect(deviceLabel(sdrsStore.state, 'usb:1-9.9')).toBe('usb:1-9.9')
  })
})
