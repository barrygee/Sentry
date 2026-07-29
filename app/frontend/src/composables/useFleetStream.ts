import { watch } from 'vue'

import type { DeviceStatus, HealthResponse, StatusResponse } from '@/api/client'
import { useFleetStore } from '@/stores/fleet'
import type { DeviceRemovedEvent, NoticeEvent } from '@/types/fleet'

import { useServerSentEvents, type ServerSentEventsHandle } from './useServerSentEvents'

/**
 * Wires the `/api/events` SSE stream (architecture §7.3) to `stores/fleet`.
 * This is the single place liveness is managed — every component renders
 * from the store, never from this composable's return value directly,
 * except to display connection state (`ConnectionPill`).
 */
export function useFleetStream(streamUrl = '/api/events'): ServerSentEventsHandle {
  const fleetStore = useFleetStore()

  const handle = useServerSentEvents(
    streamUrl,
    {
      snapshot: (data) => fleetStore.applySnapshot(data as StatusResponse),
      device_changed: (data) => fleetStore.applyDeviceChanged(data as DeviceStatus),
      device_removed: (data) =>
        fleetStore.applyDeviceRemoved((data as DeviceRemovedEvent).device_id),
      health: (data) => fleetStore.applyHealth(data as HealthResponse),
      notice: (data) => fleetStore.applyNotice(data as NoticeEvent),
    },
    {
      onMalformedEvent: (eventName, _raw, error) => {
        fleetStore.applyNotice({
          level: 'warn',
          code: 'malformed_event',
          message: `Received a malformed "${eventName}" event from the server: ${
            error instanceof Error ? error.message : String(error)
          }`,
          device_id: null,
          ts: Date.now(),
        })
      },
    },
  )

  // Mirror connection state into the store so any component can read
  // `fleetStore.connection` without importing this composable directly.
  watch(
    handle.connection,
    (nextConnection) => {
      fleetStore.setConnection(nextConnection)
    },
    { immediate: true },
  )

  return handle
}
