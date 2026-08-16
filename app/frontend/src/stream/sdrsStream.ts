import type { DeviceStatus, HealthResponse, StatusResponse } from '../api/client.js'
import { consoleAuthStore } from '../state/consoleAuth.js'
import * as hotspotStore from '../state/hotspotStore.js'
import * as sdrsStore from '../state/sdrsStore.js'
import * as wiredStore from '../state/wiredStore.js'
import type { DeviceRemovedEvent, NoticeEvent } from '../types/sdrs.js'

import { openServerSentEvents, type ServerSentEventsHandle } from './serverSentEvents.js'

/**
 * Wires the `/api/events` SSE stream (architecture §7.3) to `state/sdrsStore.ts`.
 * This is the single place liveness is managed — every module renders from
 * the store, never from this stream's handle directly, except to display
 * connection state (`ConnectionPill`).
 */
export function openSdrsStream(streamPath = '/api/events'): ServerSentEventsHandle {
  // No credential in the URL. `EventSource` cannot set headers, which used to
  // force the token into `?access_token=` — and therefore into browser history
  // and the access log. The session is a cookie now (ADR-0010), and the browser
  // attaches it to this same-origin request unasked.
  const handle = openServerSentEvents(
    streamPath,
    {
      snapshot: (data) => sdrsStore.applySnapshot(data as StatusResponse),
      device_changed: (data) => sdrsStore.applyDeviceChanged(data as DeviceStatus),
      device_removed: (data) =>
        sdrsStore.applyDeviceRemoved((data as DeviceRemovedEvent).device_id),
      health: (data) => sdrsStore.applyHealth(data as HealthResponse),
      notice: (data) => {
        const notice = data as NoticeEvent
        sdrsStore.applyNotice(notice)
        // A rollback happens on the server's timer, not in response to
        // anything this tab did, so it has to be surfaced wherever the operator
        // happens to be — including on another screen entirely. Routed here
        // rather than inside the SDRs store so that store keeps knowing nothing
        // about either network feature.
        if (notice.code === 'hotspot_rollback' || notice.code === 'hotspot_rollback_failed') {
          hotspotStore.handleRollbackNotice(notice.message)
        }
        // The wired share runs the same commit-confirm flow (ADR-0014), and its
        // rollback is the more urgent of the two to surface: it means the Pi has
        // just been put back on the LAN and the cabled machine's address is gone.
        if (notice.code === 'wired_rollback' || notice.code === 'wired_rollback_failed') {
          wiredStore.handleRollbackNotice(notice.message)
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

  // Reopen once the operator signs in. The stream is refused while signed out,
  // and `EventSource` retries a failed connection forever without ever
  // re-reading cookies it never sent — so without this the console would sit
  // offline behind a successful login until the page was reloaded.
  let wasAuthenticated = consoleAuthStore.state.authenticated
  consoleAuthStore.subscribe((nextState) => {
    if (nextState.authenticated && !wasAuthenticated) {
      handle.reopen()
    }
    wasAuthenticated = nextState.authenticated
  })

  return handle
}
