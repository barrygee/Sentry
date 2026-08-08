import type { DeviceStatus, HealthResponse, StatusResponse } from '../api/client.js'
import { authTokenStore } from '../state/authToken.js'
import * as hotspotStore from '../state/hotspotStore.js'
import * as sdrsStore from '../state/sdrsStore.js'
import type { DeviceRemovedEvent, NoticeEvent } from '../types/sdrs.js'

import { openServerSentEvents, type ServerSentEventsHandle } from './serverSentEvents.js'

/**
 * Wires the `/api/events` SSE stream (architecture §7.3) to `state/sdrsStore.ts`.
 * This is the single place liveness is managed — every module renders from
 * the store, never from this stream's handle directly, except to display
 * connection state (`ConnectionPill`).
 */
export function openSdrsStream(streamPath = '/api/events'): ServerSentEventsHandle {
  // `EventSource` cannot set an `Authorization` header, so an operator token
  // is appended as `?access_token=` (architecture §7.9) — the same fallback
  // `require_sse_bearer_token` accepts server-side.
  function streamUrl(): string {
    const token = authTokenStore.state.token
    return token ? `${streamPath}?access_token=${encodeURIComponent(token)}` : streamPath
  }

  const handle = openServerSentEvents(
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
          hotspotStore.handleRollbackNotice(notice.message)
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

  // Mirror connection state into the store so any module can read
  // `sdrsStore.state.connection` without importing this stream directly.
  sdrsStore.setConnection(handle.getConnection())
  handle.subscribeConnection((nextConnection) => {
    sdrsStore.setConnection(nextConnection)
  })

  // Reopen with the new URL whenever the auth token changes — e.g. an
  // operator supplying `SENTRY_AUTH_TOKEN` after a 401 (architecture §7.9)
  // reconnects with `?access_token=` rather than staying wedged offline.
  let previousToken = authTokenStore.state.token
  authTokenStore.subscribe((nextState) => {
    if (nextState.token !== previousToken) {
      previousToken = nextState.token
      handle.reopen()
    }
  })

  return handle
}
