import type { DeviceStatus, HealthResponse } from '@/api/client'

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

/** A node in the USB topology tree derived from `DeviceStatus.usb.port_chain`. */
export interface TopologyNode {
  /** Stable identity for the node: the USB path prefix it represents, e.g. "1-1.4". */
  path: string
  /** True when this node is a hub (has children) rather than a dongle leaf. */
  isHub: boolean
  /** The device occupying this node, when it is a leaf. */
  device: DeviceStatus | null
  children: TopologyNode[]
}

export type HealthSnapshot = HealthResponse
