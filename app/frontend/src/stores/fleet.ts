import { defineStore } from 'pinia'

import {
  apiClient,
  ApiError,
  type DeviceStatus,
  type DevicePatch,
  type PortConstraints,
  type SerialFlashAccepted,
} from '@/api/client'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import type {
  ConnectionState,
  HealthSnapshot,
  NoticeEvent,
  NoticeItem,
  TopologyNode,
} from '@/types/fleet'
import { buildTopologyTree } from '@/utils/topology'

const MAX_NOTICES = 50

export interface FleetState {
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
 * The authoritative client-side fleet model (architecture §9.2). Never opens
 * the `EventSource` itself — `useFleetStream` owns that subscription and
 * calls these actions, keeping the store trivially testable with plain
 * fixture objects.
 */
export const useFleetStore = defineStore('fleet', {
  state: (): FleetState => ({
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
  }),

  getters: {
    devices(state): DeviceStatus[] {
      return state.order
        .map((deviceId) => state.devicesById[deviceId])
        .filter((device): device is DeviceStatus => device !== undefined)
    },
    presentDevices(): DeviceStatus[] {
      return this.devices.filter((device) => device.present)
    },
    absentConfiguredDevices(): DeviceStatus[] {
      return this.devices.filter((device) => !device.present && device.record_id !== null)
    },
    unidentifiedDevices(): DeviceStatus[] {
      return this.devices.filter((device) => device.needs_identification)
    },
    topologyTree(): { roots: TopologyNode[]; unplaced: DeviceStatus[] } {
      return buildTopologyTree(this.devices)
    },
    portsInUse(): number[] {
      return this.devices
        .flatMap((device) =>
          device.output ? [device.output.iq_port, device.output.control_port] : [],
        )
        .sort((a, b) => a - b)
    },
    streamingCount(): number {
      return this.devices.filter((device) => device.state === 'streaming').length
    },
    hasErrors(): boolean {
      return this.devices.some((device) => device.state === 'error')
    },
    isDeviceBusy() {
      return (deviceId: string): boolean => {
        const device = this.devicesById[deviceId]
        return device !== undefined && (device.state === 'starting' || device.state === 'streaming')
      }
    },
    /** The device `SerialFlashDialog` should render for, derived from `serialFlashDeviceId`. */
    serialFlashDialogDevice(state): DeviceStatus | null {
      if (state.serialFlashDeviceId === null) return null
      return this.devicesById[state.serialFlashDeviceId] ?? null
    },
    /** The device `ForgetDeviceDialog` should render for, derived from `forgetDeviceId`. */
    forgetDialogDevice(state): DeviceStatus | null {
      if (state.forgetDeviceId === null) return null
      return this.devicesById[state.forgetDeviceId] ?? null
    },
    /**
     * Groups present devices that report the same raw factory serial
     * (architecture §5.1 tier 3's first cause) so `SerialConflictBanner` can
     * surface one fleet-level summary per duplicate rather than relying on
     * each affected card's `NeedsIdentificationNotice` alone.
     */
    serialConflictGroups(): { serial: string; devices: SerialConflictDevice[] }[] {
      const devicesBySerial = new Map<string, DeviceStatus[]>()
      for (const device of this.presentDevices) {
        const serial = device.usb?.serial
        if (!serial) continue
        const group = devicesBySerial.get(serial) ?? []
        group.push(device)
        devicesBySerial.set(serial, group)
      }
      return Array.from(devicesBySerial.entries())
        .filter(([, devices]) => devices.length > 1)
        .map(([serial, devices]) => ({
          serial,
          devices: devices.map((device) => ({
            deviceId: device.device_id,
            label: device.name || device.device_id,
          })),
        }))
    },
  },

  actions: {
    /** Wholesale replace on connect/reconnect — the `snapshot` SSE event and initial `GET /api/status`. */
    applySnapshot(payload: { generated_at: number; sdrs: DeviceStatus[] }): void {
      const devicesById: Record<string, DeviceStatus> = {}
      const order = [...payload.sdrs]
        .sort((deviceA, deviceB) => compareByTopology(deviceA, deviceB))
        .map((device) => {
          devicesById[device.device_id] = device
          return device.device_id
        })
      this.devicesById = devicesById
      this.order = order
      this.lastSnapshotAt = payload.generated_at
    },

    /** Merge one device on `device_changed`, clearing its pending optimistic patch on a match. */
    applyDeviceChanged(device: DeviceStatus): void {
      const isNew = this.devicesById[device.device_id] === undefined
      this.devicesById = { ...this.devicesById, [device.device_id]: device }
      if (isNew) {
        this.order = [...this.order, device.device_id].sort((idA, idB) => {
          const deviceA = this.devicesById[idA]
          const deviceB = this.devicesById[idB]
          if (!deviceA || !deviceB) return 0
          return compareByTopology(deviceA, deviceB)
        })
      }
      const pending = this.pendingPatchesByDeviceId[device.device_id]
      if (pending && patchIsSatisfiedBy(pending, device)) {
        const rest = { ...this.pendingPatchesByDeviceId }
        delete rest[device.device_id]
        this.pendingPatchesByDeviceId = rest
      }
    },

    /** An unconfigured device was unplugged — configured devices never leave the store (they go `stopped`). */
    applyDeviceRemoved(deviceId: string): void {
      if (this.devicesById[deviceId] === undefined) {
        return
      }
      const rest = { ...this.devicesById }
      delete rest[deviceId]
      this.devicesById = rest
      this.order = this.order.filter((id) => id !== deviceId)
    },

    applyHealth(payload: HealthSnapshot): void {
      this.health = payload
    },

    applyNotice(notice: NoticeEvent): void {
      noticeSequence += 1
      const item: NoticeItem = { ...notice, id: `${notice.ts}-${noticeSequence}`, dismissed: false }
      const next = [item, ...this.notices]
      this.notices = next.slice(0, MAX_NOTICES)
    },

    dismissNotice(id: string): void {
      const notice = this.notices.find((candidate) => candidate.id === id)
      if (notice) {
        notice.dismissed = true
      }
    },

    setConnection(state: ConnectionState): void {
      this.connection = state
    },

    /** Optimistic PATCH: applies the intended fields immediately, rolls back and raises a notice on failure. */
    async patchDevice(deviceId: string, patch: DevicePatch): Promise<void> {
      const previous = this.devicesById[deviceId]
      this.pendingPatchesByDeviceId = { ...this.pendingPatchesByDeviceId, [deviceId]: patch }
      if (previous) {
        this.devicesById = {
          ...this.devicesById,
          [deviceId]: applyOptimisticPatch(previous, patch),
        }
      }
      try {
        await apiClient.patchDevice(deviceId, patch)
        // Success is otherwise silent — without this a screen-reader user
        // can't distinguish a saved edit from one that failed upstream of
        // client-side validation (architecture §9.4 forms rule).
        useLiveAnnouncer().announcePolite(describePatchForAnnouncement(patch))
      } catch (error) {
        if (previous) {
          this.devicesById = { ...this.devicesById, [deviceId]: previous }
        }
        const rest = { ...this.pendingPatchesByDeviceId }
        delete rest[deviceId]
        this.pendingPatchesByDeviceId = rest
        const code =
          error instanceof ApiError ? (error.detail?.code ?? 'patch_failed') : 'patch_failed'
        this.applyNotice({
          level: 'error',
          code,
          message: humanizePatchErrorCode(code) ?? messageOf(error, 'Failed to update device.'),
          device_id: deviceId,
          ts: Date.now(),
        })
        throw error
      }
    },

    /** Begin the guarded serial-flash flow; returns the `202` body so the dialog can show `requires_replug`. */
    async flashSerial(deviceId: string, serial: string): Promise<SerialFlashAccepted> {
      try {
        return await apiClient.flashSerial(deviceId, { serial, confirm: true })
      } catch (error) {
        this.applyNotice({
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
    },

    /**
     * Discards a device's persisted configuration ("forgetting" it). Only
     * ever called for an absent, configured device — the server itself
     * refuses (`409 device_present`) while the hardware is plugged in, which
     * surfaces here as a thrown `ApiError` the caller (`ForgetDeviceDialog`)
     * humanizes for the race where the dongle replugged mid-dialog.
     */
    async deleteDevice(deviceId: string): Promise<void> {
      const device = this.devicesById[deviceId]
      const label = device?.name || deviceId
      try {
        await apiClient.deleteDevice(deviceId)
        this.applyDeviceRemoved(deviceId)
        this.closeForgetDialog()
        useLiveAnnouncer().announcePolite(`Forgot ${label}.`)
      } catch (error) {
        const code =
          error instanceof ApiError ? (error.detail?.code ?? 'delete_failed') : 'delete_failed'
        this.applyNotice({
          level: 'error',
          code,
          message: humanizeDeleteErrorCode(code) ?? messageOf(error, 'Failed to forget device.'),
          device_id: deviceId,
          ts: Date.now(),
        })
        throw error
      }
    },

    setConstraints(constraints: PortConstraints): void {
      this.constraints = constraints
    },

    /** Opens `SerialFlashDialog` for `deviceId` — called from a topology node, device card or conflict banner. */
    openSerialFlashDialog(deviceId: string): void {
      this.serialFlashDeviceId = deviceId
    },

    closeSerialFlashDialog(): void {
      this.serialFlashDeviceId = null
    },

    /** Opens `ForgetDeviceDialog` for `deviceId` — called only from an absent, configured device's card. */
    openForgetDialog(deviceId: string): void {
      this.forgetDeviceId = deviceId
    },

    closeForgetDialog(): void {
      this.forgetDeviceId = null
    },
  },
})

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
  return true
}

function applyOptimisticPatch(device: DeviceStatus, patch: DevicePatch): DeviceStatus {
  return {
    ...device,
    name: patch.name ?? device.name,
    enabled: patch.enabled ?? device.enabled,
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
