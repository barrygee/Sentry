import type { DeviceState } from '@/api/client'

export type { DeviceState }

export interface DeviceStateMeta {
  label: string
  glyph: string
  textColorClass: string
}

/** States in which a device holds no live process pair — the only states the guarded EEPROM serial flash (architecture §7.6 guard 4) may run from. */
export const IDLE_DEVICE_STATES: readonly DeviceState[] = ['detected', 'configured', 'stopped']

/** Whether `state` is idle enough to permit a serial flash — mirrors the server's own guard so the UI never invites a request it knows will be rejected. */
export function isDeviceIdle(state: DeviceState): boolean {
  return IDLE_DEVICE_STATES.includes(state)
}

/**
 * The single source of truth for a device state's colour, glyph and label
 * (architecture §9.5 semantics table), read by `StatusDot` and through it by
 * every badge. Colour alone never carries the meaning: every entry also has a
 * distinct glyph and label text — which is what let the device card's coloured
 * left stripe be removed without losing information.
 */
export const DEVICE_STATE_META: Record<DeviceState, DeviceStateMeta> = {
  streaming: {
    label: 'Streaming',
    glyph: '●',
    textColorClass: 'text-signal-accent',
  },
  degraded: {
    label: 'Degraded',
    glyph: '▲',
    textColorClass: 'text-signal-warn',
  },
  error: {
    label: 'Error',
    glyph: '✕',
    textColorClass: 'text-signal-danger',
  },
  starting: {
    label: 'Starting',
    glyph: '◐',
    textColorClass: 'text-signal-info',
  },
  configured: {
    label: 'Configured',
    glyph: '○',
    textColorClass: 'text-signal-muted',
  },
  detected: {
    label: 'Detected',
    glyph: '◇',
    textColorClass: 'text-signal-muted',
  },
  stopped: {
    label: 'Stopped',
    glyph: '■',
    textColorClass: 'text-signal-muted',
  },
}
