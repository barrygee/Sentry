export type DeviceState =
  'detected' | 'configured' | 'starting' | 'streaming' | 'degraded' | 'stopped' | 'error'

export interface DeviceStateMeta {
  label: string
  glyph: string
  textColorClass: string
  borderColorClass: string
}

/**
 * The single source of truth for a device state's colour, glyph and label
 * (architecture §9.5 semantics table) — `StatusDot` and `SdrDeviceCard`'s
 * state stripe both read from here so the two can never drift apart.
 */
/** States in which a device holds no live process pair — the only states the guarded EEPROM serial flash (architecture §7.6 guard 4) may run from. */
export const IDLE_DEVICE_STATES: readonly DeviceState[] = ['detected', 'configured', 'stopped']

/** Whether `state` is idle enough to permit a serial flash — mirrors the server's own guard so the UI never invites a request it knows will be rejected. */
export function isDeviceIdle(state: DeviceState): boolean {
  return IDLE_DEVICE_STATES.includes(state)
}

export const DEVICE_STATE_META: Record<DeviceState, DeviceStateMeta> = {
  streaming: {
    label: 'Streaming',
    glyph: '●',
    textColorClass: 'text-signal-lime',
    borderColorClass: 'border-signal-lime',
  },
  degraded: {
    label: 'Degraded',
    glyph: '▲',
    textColorClass: 'text-signal-amber',
    borderColorClass: 'border-signal-amber',
  },
  error: {
    label: 'Error',
    glyph: '✕',
    textColorClass: 'text-signal-red',
    borderColorClass: 'border-signal-red',
  },
  starting: {
    label: 'Starting',
    glyph: '◐',
    textColorClass: 'text-signal-cyan',
    borderColorClass: 'border-signal-cyan',
  },
  configured: {
    label: 'Configured',
    glyph: '○',
    textColorClass: 'text-signal-slate',
    borderColorClass: 'border-signal-slateMuted',
  },
  detected: {
    label: 'Detected',
    glyph: '◇',
    textColorClass: 'text-signal-slate',
    borderColorClass: 'border-signal-slateMuted',
  },
  stopped: {
    label: 'Stopped',
    glyph: '■',
    textColorClass: 'text-signal-slate',
    borderColorClass: 'border-signal-slateMuted',
  },
}
