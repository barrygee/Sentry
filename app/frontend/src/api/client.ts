import { useAuthToken } from '@/composables/useAuthToken'

import type { components } from './types'

export type DeviceStatus = components['schemas']['DeviceStatus']
/** The generated device-state union — the single source of truth every component/store imports rather than redeclaring. */
export type DeviceState = DeviceStatus['state']
export type DevicePatch = components['schemas']['DevicePatch']
export type DeviceRecord = components['schemas']['DeviceRecord']
export type StatusResponse = components['schemas']['StatusResponse']
export type HealthResponse = components['schemas']['HealthResponse']
export type PortConstraints = components['schemas']['PortConstraints']
export type SerialFlashRequest = components['schemas']['SerialFlashRequest']
export type SerialFlashAccepted = components['schemas']['SerialFlashAccepted']

/** Machine-readable shape of a `{"detail": {...}}` error body (architecture §7). */
export interface ApiErrorDetail {
  code: string
  message?: string
  [key: string]: unknown
}

/** Thrown by every `apiClient` method on a non-2xx response. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: ApiErrorDetail | null

  constructor(status: number, detail: ApiErrorDetail | null, fallbackMessage: string) {
    super(detail?.message ?? fallbackMessage)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<ResponseBody>(path: string, init?: RequestInit): Promise<ResponseBody> {
  const { token, requirePrompt } = useAuthToken()
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token.value ? { Authorization: `Bearer ${token.value}` } : {}),
      ...init?.headers,
    },
  })

  if (response.status === 401) {
    // Surfaces `AuthTokenPrompt` (architecture §7.9) — this fetch still
    // fails and throws below, but the operator now has an in-app way to
    // supply the token rather than a silently-dead console.
    requirePrompt()
  }

  if (!response.ok) {
    let detail: ApiErrorDetail | null = null
    try {
      const body: unknown = await response.json()
      if (isDetailBody(body)) {
        detail = body.detail
      }
    } catch {
      // Non-JSON error body — detail stays null, the ApiError falls back to a generic message.
    }
    throw new ApiError(response.status, detail, `Request to ${path} failed (${response.status})`)
  }

  if (response.status === 204) {
    return undefined as ResponseBody
  }
  return (await response.json()) as ResponseBody
}

function isDetailBody(value: unknown): value is { detail: ApiErrorDetail } {
  return (
    typeof value === 'object' &&
    value !== null &&
    'detail' in value &&
    typeof (value as { detail: unknown }).detail === 'object' &&
    (value as { detail: unknown }).detail !== null
  )
}

/** Thin, typed wrapper over the Sentry internal UI API (architecture §7). */
export const apiClient = {
  getStatus: () => request<StatusResponse>('/status'),
  getHealth: () => request<HealthResponse>('/health'),
  listDevices: () => request<components['schemas']['DevicesListResponse']>('/devices'),
  patchDevice: (deviceId: string, patch: DevicePatch) =>
    request<DeviceRecord>(`/devices/${encodeURIComponent(deviceId)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteDevice: (deviceId: string) =>
    request<void>(`/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' }),
  flashSerial: (deviceId: string, body: SerialFlashRequest) =>
    request<SerialFlashAccepted>(`/devices/${encodeURIComponent(deviceId)}/serial`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}
