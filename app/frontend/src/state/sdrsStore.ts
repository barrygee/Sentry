import {
  apiClient,
  ApiError,
  type DeviceStatus,
  type DevicePatch,
  type PortConstraints,
  type SerialFlashAccepted,
} from '../api/client.js'
import { liveAnnouncer } from '../core/liveAnnouncer.js'
import { createStore, type Store } from '../core/observable.js'
import type { ConnectionState, HealthSnapshot, NoticeEvent, NoticeItem } from '../types/sdrs.js'

const MAX_NOTICES = 50

export interface SdrsState {
  devicesById: Record<string, DeviceStatus>
  order: string[]
  health: HealthSnapshot | null
  constraints: PortConstraints | null
  connection: ConnectionState
  lastSnapshotAt: number | null
  pendingPatchesByDeviceId: Record<string, DevicePatch>
  notices: NoticeItem[]
  /** The device the `SerialFlashDialog` is currently open for, or `null` when it is closed.
   * Lives here rather than in a component ref because the dialog is teleported to `<body>` —
   * whichever control invoked it (a topology node, a device card, a conflict banner) needs a
   * single shared place to open it from. */
  serialFlashDeviceId: string | null
  /** The device `ForgetDeviceDialog` is currently open for, or `null` when it is closed. Lives
   * here for the same reason as `serialFlashDeviceId` — the invoking control (a card inside
   * `AbsentDeviceGroup`) and the teleported dialog need a single shared source of truth. */
  forgetDeviceId: string | null
}

/** One entry in `serialConflictGroups`: a present device sharing a duplicate factory serial. */
export interface SerialConflictDevice {
  deviceId: string
  label: string
}

let noticeSequence = 0

/**
 * The authoritative client-side SDR model (architecture §9.2). Never opens
 * the `EventSource` itself — `sdrsStream.ts` owns that subscription and
 * calls these actions, keeping the store trivially testable with plain
 * fixture objects.
 */
export const sdrsStore: Store<SdrsState> = createStore<SdrsState>({
  devicesById: {},
  order: [],
  health: null,
  constraints: null,
  connection: 'connecting',
  lastSnapshotAt: null,
  pendingPatchesByDeviceId: {},
  notices: [],
  serialFlashDeviceId: null,
  forgetDeviceId: null,
})

/** All known devices, in topology order. */
export function devices(state: Readonly<SdrsState>): DeviceStatus[] {
  return state.order
    .map((deviceId) => state.devicesById[deviceId])
    .filter((device): device is DeviceStatus => device !== undefined)
}

/** Devices currently physically plugged in. */
export function presentDevices(state: Readonly<SdrsState>): DeviceStatus[] {
  return devices(state).filter((device) => device.present)
}

/** Configured devices that are not currently plugged in. */
export function absentConfiguredDevices(state: Readonly<SdrsState>): DeviceStatus[] {
  return devices(state).filter((device) => !device.present && device.record_id !== null)
}

/** Devices whose physical index could not be resolved and need operator identification. */
export function unidentifiedDevices(state: Readonly<SdrsState>): DeviceStatus[] {
  return devices(state).filter((device) => device.needs_identification)
}

/** Every IQ/control port currently claimed by a configured device, sorted ascending. */
export function portsInUse(state: Readonly<SdrsState>): number[] {
  return devices(state)
    .flatMap((device) => (device.output ? [device.output.iq_port, device.output.control_port] : []))
    .sort((portA, portB) => portA - portB)
}

/** Whether any known device currently reports an error state. */
export function hasErrors(state: Readonly<SdrsState>): boolean {
  return devices(state).some((device) => device.state === 'error')
}

/** Whether the given device is mid-lifecycle and its controls should be treated as busy. */
export function isDeviceBusy(state: Readonly<SdrsState>, deviceId: string): boolean {
  const device = state.devicesById[deviceId]
  return device !== undefined && (device.state === 'starting' || device.state === 'streaming')
}

/** The device `SerialFlashDialog` should render for, derived from `serialFlashDeviceId`. */
export function serialFlashDialogDevice(state: Readonly<SdrsState>): DeviceStatus | null {
  if (state.serialFlashDeviceId === null) return null
  return state.devicesById[state.serialFlashDeviceId] ?? null
}

/** The device `ForgetDeviceDialog` should render for, derived from `forgetDeviceId`. */
export function forgetDialogDevice(state: Readonly<SdrsState>): DeviceStatus | null {
  if (state.forgetDeviceId === null) return null
  return state.devicesById[state.forgetDeviceId] ?? null
}

/**
 * Groups present devices that report the same raw factory serial
 * (architecture §5.1 tier 3's first cause) so `SerialConflictBanner` can
 * surface one SDR-level summary per duplicate rather than relying on
 * each affected card's `NeedsIdentificationNotice` alone.
 */
export function serialConflictGroups(
  state: Readonly<SdrsState>,
): { serial: string; devices: SerialConflictDevice[] }[] {
  const devicesBySerial = new Map<string, DeviceStatus[]>()
  for (const device of presentDevices(state)) {
    const serial = device.usb?.serial
    if (!serial) continue
    const group = devicesBySerial.get(serial) ?? []
    group.push(device)
    devicesBySerial.set(serial, group)
  }
  return Array.from(devicesBySerial.entries())
    .filter(([, groupedDevices]) => groupedDevices.length > 1)
    .map(([serial, groupedDevices]) => ({
      serial,
      devices: groupedDevices.map((device) => ({
        deviceId: device.device_id,
        label: device.name || device.device_id,
      })),
    }))
}

/** Wholesale replace on connect/reconnect — the `snapshot` SSE event and initial `GET /api/status`. */
export function applySnapshot(payload: { generated_at: number; sdrs: DeviceStatus[] }): void {
  const devicesById: Record<string, DeviceStatus> = {}
  const order = [...payload.sdrs]
    .sort((deviceA, deviceB) => compareByTopology(deviceA, deviceB))
    .map((device) => {
      devicesById[device.device_id] = device
      return device.device_id
    })
  sdrsStore.setState({ devicesById, order, lastSnapshotAt: payload.generated_at })
}

/** Merge one device on `device_changed`, clearing its pending optimistic patch on a match. */
export function applyDeviceChanged(device: DeviceStatus): void {
  const current = sdrsStore.state
  const isNew = current.devicesById[device.device_id] === undefined
  const devicesById = { ...current.devicesById, [device.device_id]: device }
  let order = current.order
  if (isNew) {
    order = [...current.order, device.device_id].sort((idA, idB) => {
      const deviceA = devicesById[idA]
      const deviceB = devicesById[idB]
      if (!deviceA || !deviceB) return 0
      return compareByTopology(deviceA, deviceB)
    })
  }
  let pendingPatchesByDeviceId = current.pendingPatchesByDeviceId
  const pending = pendingPatchesByDeviceId[device.device_id]
  if (pending && patchIsSatisfiedBy(pending, device)) {
    const rest = { ...pendingPatchesByDeviceId }
    delete rest[device.device_id]
    pendingPatchesByDeviceId = rest
  }
  sdrsStore.setState({ devicesById, order, pendingPatchesByDeviceId })
}

/** An unconfigured device was unplugged — configured devices never leave the store (they go `stopped`). */
export function applyDeviceRemoved(deviceId: string): void {
  const current = sdrsStore.state
  if (current.devicesById[deviceId] === undefined) {
    return
  }
  const rest = { ...current.devicesById }
  delete rest[deviceId]
  sdrsStore.setState({
    devicesById: rest,
    order: current.order.filter((id) => id !== deviceId),
  })
}

/** Applies a fresh health snapshot as received from the `health` SSE event. */
export function applyHealth(payload: HealthSnapshot): void {
  sdrsStore.setState({ health: payload })
}

/** Appends a notice to the capped, drop-oldest notice log. */
export function applyNotice(notice: NoticeEvent): void {
  noticeSequence += 1
  const item: NoticeItem = { ...notice, id: `${notice.ts}-${noticeSequence}`, dismissed: false }
  const next = [item, ...sdrsStore.state.notices]
  sdrsStore.setState({ notices: next.slice(0, MAX_NOTICES) })
}

/** Marks a notice dismissed by id, leaving the rest of the log untouched. */
export function dismissNotice(id: string): void {
  const notices = sdrsStore.state.notices.map((notice) =>
    notice.id === id ? { ...notice, dismissed: true } : notice,
  )
  sdrsStore.setState({ notices })
}

/** Records the SSE stream's current connection state. */
export function setConnection(connectionState: ConnectionState): void {
  sdrsStore.setState({ connection: connectionState })
}

/** Optimistic PATCH: applies the intended fields immediately, rolls back and raises a notice on failure. */
export async function patchDevice(deviceId: string, patch: DevicePatch): Promise<void> {
  const current = sdrsStore.state
  const previous = current.devicesById[deviceId]
  sdrsStore.setState({
    pendingPatchesByDeviceId: { ...current.pendingPatchesByDeviceId, [deviceId]: patch },
    devicesById: previous
      ? { ...current.devicesById, [deviceId]: applyOptimisticPatch(previous, patch) }
      : current.devicesById,
  })
  try {
    await apiClient.patchDevice(deviceId, patch)
    // Success is otherwise silent — without this a screen-reader user
    // can't distinguish a saved edit from one that failed upstream of
    // client-side validation (architecture §9.4 forms rule).
    liveAnnouncer().announcePolite(describePatchForAnnouncement(patch))
  } catch (error) {
    const rest = { ...sdrsStore.state.pendingPatchesByDeviceId }
    delete rest[deviceId]
    sdrsStore.setState({
      devicesById: previous
        ? { ...sdrsStore.state.devicesById, [deviceId]: previous }
        : sdrsStore.state.devicesById,
      pendingPatchesByDeviceId: rest,
    })
    const code = error instanceof ApiError ? (error.detail?.code ?? 'patch_failed') : 'patch_failed'
    applyNotice({
      level: 'error',
      code,
      message: humanizePatchErrorCode(code) ?? messageOf(error, 'Failed to update device.'),
      device_id: deviceId,
      ts: Date.now(),
    })
    throw error
  }
}

/** Begin the guarded serial-flash flow; returns the `202` body so the dialog can show `requires_replug`. */
export async function flashSerial(deviceId: string, serial: string): Promise<SerialFlashAccepted> {
  try {
    return await apiClient.flashSerial(deviceId, { serial, confirm: true })
  } catch (error) {
    applyNotice({
      level: 'error',
      code:
        error instanceof ApiError
          ? (error.detail?.code ?? 'serial_flash_failed')
          : 'serial_flash_failed',
      message: error instanceof Error ? error.message : 'Failed to flash serial.',
      device_id: deviceId,
      ts: Date.now(),
    })
    throw error
  }
}

/**
 * Discards a device's persisted configuration ("forgetting" it). Only
 * ever called for an absent, configured device — the server itself
 * refuses (`409 device_present`) while the hardware is plugged in, which
 * surfaces here as a thrown `ApiError` the caller (`ForgetDeviceDialog`)
 * humanizes for the race where the dongle replugged mid-dialog.
 */
export async function deleteDevice(deviceId: string): Promise<void> {
  const device = sdrsStore.state.devicesById[deviceId]
  const label = device?.name || deviceId
  try {
    await apiClient.deleteDevice(deviceId)
    applyDeviceRemoved(deviceId)
    closeForgetDialog()
    liveAnnouncer().announcePolite(`Forgot ${label}.`)
  } catch (error) {
    const code =
      error instanceof ApiError ? (error.detail?.code ?? 'delete_failed') : 'delete_failed'
    applyNotice({
      level: 'error',
      code,
      message: humanizeDeleteErrorCode(code) ?? messageOf(error, 'Failed to forget device.'),
      device_id: deviceId,
      ts: Date.now(),
    })
    throw error
  }
}

/** Records the port-usage constraints reported by `GET /api/devices`. */
export function setConstraints(constraints: PortConstraints): void {
  sdrsStore.setState({ constraints })
}

/** Opens `SerialFlashDialog` for `deviceId` — called from a topology node, device card or conflict banner. */
export function openSerialFlashDialog(deviceId: string): void {
  sdrsStore.setState({ serialFlashDeviceId: deviceId })
}

/** Closes `SerialFlashDialog`. */
export function closeSerialFlashDialog(): void {
  sdrsStore.setState({ serialFlashDeviceId: null })
}

/** Opens `ForgetDeviceDialog` for `deviceId` — called only from an absent, configured device's card. */
export function openForgetDialog(deviceId: string): void {
  sdrsStore.setState({ forgetDeviceId: deviceId })
}

/** Closes `ForgetDeviceDialog`. */
export function closeForgetDialog(): void {
  sdrsStore.setState({ forgetDeviceId: null })
}

function compareByTopology(deviceA: DeviceStatus, deviceB: DeviceStatus): number {
  const pathA = deviceA.usb?.topology_path ?? deviceA.usb_last_known?.topology_path ?? null
  const pathB = deviceB.usb?.topology_path ?? deviceB.usb_last_known?.topology_path ?? null
  if (pathA === null && pathB === null) return 0
  if (pathA === null) return 1
  if (pathB === null) return -1
  return pathA.localeCompare(pathB, undefined, { numeric: true })
}

/** Only clears a pending patch once the server-confirmed device reflects every patched field. */
function patchIsSatisfiedBy(patch: DevicePatch, device: DeviceStatus): boolean {
  if (patch.name !== undefined && patch.name !== null && device.name !== patch.name) return false
  if (patch.enabled !== undefined && patch.enabled !== null && device.enabled !== patch.enabled)
    return false
  if (
    patch.output_port !== undefined &&
    patch.output_port !== null &&
    device.output?.iq_port !== patch.output_port
  ) {
    return false
  }
  if (
    patch.visibility !== undefined &&
    patch.visibility !== null &&
    device.visibility !== patch.visibility
  ) {
    return false
  }
  // `''` is a real value for both of these (it clears the field), so they are
  // compared against `undefined`/`null` only — a `!patch.notes` shortcut would
  // treat "cleared" as "not patched" and leave the pending patch stuck.
  if (patch.antenna !== undefined && patch.antenna !== null && device.antenna !== patch.antenna) {
    return false
  }
  if (patch.notes !== undefined && patch.notes !== null && device.notes !== patch.notes) {
    return false
  }
  return true
}

function applyOptimisticPatch(device: DeviceStatus, patch: DevicePatch): DeviceStatus {
  return {
    ...device,
    name: patch.name ?? device.name,
    enabled: patch.enabled ?? device.enabled,
    visibility: patch.visibility ?? device.visibility,
    antenna: patch.antenna ?? device.antenna,
    notes: patch.notes ?? device.notes,
  }
}

/** A short, operator-facing sentence describing a committed patch, for the polite live region. */
function describePatchForAnnouncement(patch: DevicePatch): string {
  const parts: string[] = []
  if (patch.name !== undefined && patch.name !== null) {
    parts.push(`name set to "${patch.name}"`)
  }
  if (patch.output_port !== undefined && patch.output_port !== null) {
    parts.push(`output port set to ${patch.output_port}`)
  }
  if (patch.enabled !== undefined && patch.enabled !== null) {
    parts.push(patch.enabled ? 'enabled' : 'disabled')
  }
  if (patch.visibility !== undefined && patch.visibility !== null) {
    // Says what the setting *does*, not just its name — "set to private" would
    // leave the operator to guess what the export contains.
    parts.push(
      patch.visibility === 'private'
        ? 'made private, no longer published to Sentinel'
        : 'published to Sentinel',
    )
  }
  if (patch.antenna !== undefined && patch.antenna !== null) {
    parts.push(patch.antenna === '' ? 'antenna cleared' : `antenna set to "${patch.antenna}"`)
  }
  if (patch.notes !== undefined && patch.notes !== null) {
    // The note itself is not read out: it can run to 2000 characters, and a
    // polite live region is the wrong place for an essay.
    parts.push(patch.notes === '' ? 'notes cleared' : 'notes saved')
  }
  return parts.length > 0 ? `Saved — ${parts.join(', ')}.` : 'Device saved.'
}

/**
 * Maps a known `PATCH /api/devices/{id}` rejection code to an operator-facing
 * sentence, returning `null` for a code with no special-cased text so the
 * caller falls back to the server's own `detail.message`.
 */
function humanizePatchErrorCode(code: string): string | null {
  switch (code) {
    case 'incomplete_configuration':
      return 'Configuring a device for the first time requires both a name and an output port in the same request.'
    case 'port_conflict':
      return 'That output port is already assigned to another device.'
    case 'port_reserved_http':
    case 'port_reserved_internal':
    case 'port_reserved_operator':
      return 'That output port is reserved and cannot be assigned to a device.'
    case 'port_in_use':
      return 'That output port is already bound on this host.'
    case 'port_out_of_range':
      return 'That output port is outside the allowed range.'
    case 'name_conflict':
      return 'That name is already used by another device.'
    case 'device_unidentified':
      return 'This device could not be resolved to a physical index. Replug it and try again.'
    case 'unknown_device':
      return 'This device is no longer known to Sentry.'
    default:
      return null
  }
}

/**
 * Maps a known `DELETE /api/devices/{id}` rejection code to an
 * operator-facing sentence, returning `null` for a code with no
 * special-cased text so the caller falls back to the server's own
 * `detail.message`.
 */
function humanizeDeleteErrorCode(code: string): string | null {
  switch (code) {
    case 'device_present':
      return 'This device came back online before it could be forgotten, so it is no longer absent.'
    case 'unknown_device':
      return 'This device is already gone.'
    default:
      return null
  }
}

/** Extracts a human message from a caught value, falling back to `fallbackMessage`. */
function messageOf(error: unknown, fallbackMessage: string): string {
  return error instanceof Error ? error.message : fallbackMessage
}
