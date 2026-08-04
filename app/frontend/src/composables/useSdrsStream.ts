import { computed, watch } from 'vue'

import type { DeviceStatus, HealthResponse, StatusResponse } from '@/api/client'
import { useAuthToken } from '@/composables/useAuthToken'
import { useSdrsStore } from '@/stores/sdrs'
import { useHotspotStore } from '@/stores/hotspot'
import type { DeviceRemovedEvent, NoticeEvent } from '@/types/sdrs'

import { useServerSentEvents, type ServerSentEventsHandle } from './useServerSentEvents'

/**
 * Wires the `/api/events` SSE stream (architecture §7.3) to `stores/sdrs`.
 * This is the single place liveness is managed — every component renders
 * from the store, never from this composable's return value directly,
 * except to display connection state (`ConnectionPill`).
 */
export function useSdrsStream(streamPath = '/api/events'): ServerSentEventsHandle {
  const sdrsStore = useSdrsStore()
  const { token } = useAuthToken()

  // `EventSource` cannot set an `Authorization` header, so an operator token
  // is appended as `?access_token=` (architecture §7.9) — the same fallback
  // `require_sse_bearer_token` accepts server-side.
  const streamUrl = computed(() =>
    token.value ? `${streamPath}?access_token=${encodeURIComponent(token.value)}` : streamPath,
  )

  const handle = useServerSentEvents(
    streamUrl,
    {
      snapshot: (data) => sdrsStore.applySnapshot(data as StatusResponse),
      device_changed: (data) => sdrsStore.applyDeviceChanged(data as DeviceStatus),
      device_removed: (data) =>
        sdrsStore.applyDeviceRemoved((data as DeviceRemovedEvent).device_id),
      health: (data) => sdrsStore.applyHealth(data as HealthResponse),
      notice: (data) => {
        const notice = data as NoticeEvent
        sdrsStore.applyNotice(notice)
        // A hotspot rollback happens on the server's timer, not in response to
        // anything this tab did, so it has to be surfaced wherever the operator
        // happens to be — including with the settings dialog closed. Routed
        // here rather than inside the SDRs store so that store keeps knowing
        // nothing about the hotspot.
        if (notice.code === 'hotspot_rollback' || notice.code === 'hotspot_rollback_failed') {
          useHotspotStore().handleRollbackNotice(notice.message)
        }
      },
    },
    {
      onMalformedEvent: (eventName, _raw, error) => {
        sdrsStore.applyNotice({
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
  // `sdrsStore.connection` without importing this composable directly.
  watch(
    handle.connection,
    (nextConnection) => {
      sdrsStore.setConnection(nextConnection)
    },
    { immediate: true },
  )

  return handle
}
