import type { HealthResponse } from '../api/client.js'

/**
 * SSE payload shapes that are documented in architecture §7.3 but are not
 * modelled in the generated OpenAPI types (the event stream itself is typed
 * `unknown` there — its named-event bodies are declared separately per the
 * frozen JSON shapes in `schemas/events.py`).
 */
export interface DeviceRemovedEvent {
  device_id: string
  record_id: number | null
}

export type NoticeLevel = 'info' | 'warn' | 'error'

export interface NoticeEvent {
  level: NoticeLevel
  code: string
  message: string
  device_id: string | null
  ts: number
}

/** One entry in the store's capped, drop-oldest notice log. */
export interface NoticeItem extends NoticeEvent {
  id: string
  dismissed: boolean
}

export type ConnectionState = 'connecting' | 'live' | 'reconnecting' | 'offline'

export type HealthSnapshot = HealthResponse
