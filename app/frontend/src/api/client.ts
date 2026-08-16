import type { components } from './types.js'

export type DeviceStatus = components['schemas']['DeviceStatus']
/** The generated device-state union — the single source of truth every component/store imports rather than redeclaring. */
export type DeviceState = DeviceStatus['state']
export type DevicePatch = components['schemas']['DevicePatch']
export type DeviceRecord = components['schemas']['DeviceRecord']
export type DevicesListResponse = components['schemas']['DevicesListResponse']
export type StatusResponse = components['schemas']['StatusResponse']
/** This Sentry's fixed position, as published to Sentinel. Both coordinates null when unset. */
export type SentryLocation = components['schemas']['SentryLocation']
export type SentryLocationUpdate = components['schemas']['SentryLocationUpdate']
export type HealthResponse = components['schemas']['HealthResponse']
export type PortConstraints = components['schemas']['PortConstraints']
export type SerialFlashRequest = components['schemas']['SerialFlashRequest']
export type SerialFlashAccepted = components['schemas']['SerialFlashAccepted']
export type HotspotState = components['schemas']['HotspotStateResponse']
export type HotspotControlResponse = components['schemas']['HotspotControlResponse']
export type HotspotConfigRequest = components['schemas']['HotspotConfigRequest']
export type HotspotActivationRequest = components['schemas']['HotspotActivationRequest']
export type HotspotClientsResponse = components['schemas']['HotspotClientsResponse']
export type HotspotClient = components['schemas']['HotspotClientItem']
export type WirelessInterface = components['schemas']['WirelessInterfaceItem']
export type WirelessInterfacesResponse = components['schemas']['WirelessInterfacesResponse']
// Wired sharing (ADR-0014). `WiredClientItem` is structurally identical to
// `HotspotClientItem` — same dnsmasq, same lease file — which is why the shared
// lease-list component takes either.
export type WiredShareState = components['schemas']['WiredShareStateResponse']
export type WiredShareConfigRequest = components['schemas']['WiredShareConfigRequest']
export type WiredShareActivationRequest = components['schemas']['WiredShareActivationRequest']
export type WiredClientsResponse = components['schemas']['WiredClientsResponse']
export type WiredClient = components['schemas']['WiredClientItem']
export type WiredInterface = components['schemas']['WiredInterfaceItem']
export type WiredInterfacesResponse = components['schemas']['WiredInterfacesResponse']
/**
 * A configuration as the server *returns* it — never carrying a hotspot
 * passphrase, which is import-only server-side.
 */
export type AuthStateResponse = components['schemas']['AuthStateResponse']
export type SentryConfig = components['schemas']['SentryConfig-Output']
/**
 * A configuration as the server *accepts* it. Differs from `SentryConfig` by
 * the optional `hotspot.passphrase`, so a file an operator hand-wrote to
 * provision a Pi types correctly on the way in. The generator splits these two
 * the moment a field is input-only; keeping both names means the direction of
 * travel is visible at each call site rather than assumed.
 */
export type SentryConfigImport = components['schemas']['SentryConfig-Input']
export type ConfigImportRequest = components['schemas']['ConfigImportRequest']
export type ConfigImportResult = components['schemas']['ConfigImportResult']
export type DeviceImportOutcome = components['schemas']['DeviceImportOutcome']

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

let unauthorizedHandler: (() => void) | null = null

/**
 * Register what happens when any request comes back `401`.
 *
 * Wired once by the composition root. A registration rather than a direct
 * import because the auth store depends on this module, and the dependency
 * cannot run both ways.
 */
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler
}

async function request<ResponseBody>(path: string, init?: RequestInit): Promise<ResponseBody> {
  const response = await fetch(`/api${path}`, {
    ...init,
    // Explicit, though it is also the default: the session is an `HttpOnly`
    // cookie (ADR-0010), so every request depends on the browser attaching it.
    // Spelling it out means a future refactor has to decide to remove it rather
    // than delete it by accident.
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (response.status === 401) {
    // The session expired, was signed out elsewhere, or the password changed.
    // Notifies via a registered handler rather than importing the auth store:
    // that store imports this module, and importing it back would be a cycle.
    // This request still fails and throws below.
    unauthorizedHandler?.()
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
  // Authentication (ADR-0010). None of these carry a credential in a header —
  // the session is a cookie the browser attaches itself.
  authState: () => request<AuthStateResponse>('/auth/state'),
  login: (password: string) =>
    request<void>('/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  setConsolePassword: (newPassword: string, currentPassword: string | null) =>
    request<void>('/auth/password', {
      method: 'POST',
      body: JSON.stringify({
        new_password: newPassword,
        // Omitted entirely rather than sent as null when setting the first
        // password, matching how the hotspot form omits an unchanged passphrase.
        ...(currentPassword === null ? {} : { current_password: currentPassword }),
      }),
    }),

  /** Switch this Sentry's hotspot control on or off without a restart (ADR-0013). */
  setHotspotControl: (enabled: boolean) =>
    request<HotspotControlResponse>('/hotspot/control', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  getStatus: () => request<StatusResponse>('/status'),

  // This Sentry's fixed position (`schemas/location.py`). A PUT, not a PATCH:
  // the body always states both coordinates, and two nulls is how the operator
  // clears the position rather than an omission meaning "leave it alone".
  getLocation: () => request<SentryLocation>('/location'),
  putLocation: (body: SentryLocationUpdate) =>
    request<SentryLocation>('/location', { method: 'PUT', body: JSON.stringify(body) }),
  getHealth: () => request<HealthResponse>('/health'),
  listDevices: () => request<DevicesListResponse>('/devices'),
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

  // Hotspot (ADR-0007). `putHotspot` takes the caller's body verbatim so that
  // omitting `passphrase` stays a meaningful, deliberate act — the store builds
  // the body without the key rather than sending `undefined`, which is what
  // keeps "leave the stored password alone" expressible over the wire.
  getHotspot: () => request<HotspotState>('/hotspot'),
  getHotspotInterfaces: () => request<WirelessInterfacesResponse>('/hotspot/interfaces'),
  getHotspotClients: () => request<HotspotClientsResponse>('/hotspot/clients'),
  putHotspot: (body: HotspotConfigRequest) =>
    request<HotspotState>('/hotspot', { method: 'PUT', body: JSON.stringify(body) }),
  enableHotspot: (body: HotspotActivationRequest) =>
    request<HotspotState>('/hotspot/enable', { method: 'POST', body: JSON.stringify(body) }),
  disableHotspot: (body: HotspotActivationRequest) =>
    request<HotspotState>('/hotspot/disable', { method: 'POST', body: JSON.stringify(body) }),
  confirmHotspot: () => request<HotspotState>('/hotspot/confirm', { method: 'POST' }),
  deleteHotspot: () => request<void>('/hotspot', { method: 'DELETE' }),

  /**
   * Ask the AP's DHCP server to forget one lease.
   *
   * Keyed by MAC alone — the server looks the address up from its own lease
   * list, so a caller cannot pair one client's MAC with another's IP.
   */
  releaseHotspotLease: (macAddress: string) =>
    request<void>(`/hotspot/clients/${encodeURIComponent(macAddress)}`, { method: 'DELETE' }),

  // Wired sharing (ADR-0014) — the same seven-route shape as the hotspot,
  // minus everything to do with a passphrase, because a wired share has none.
  getWired: () => request<WiredShareState>('/wired'),
  getWiredInterfaces: () => request<WiredInterfacesResponse>('/wired/interfaces'),
  getWiredClients: () => request<WiredClientsResponse>('/wired/clients'),
  putWired: (body: WiredShareConfigRequest) =>
    request<WiredShareState>('/wired', { method: 'PUT', body: JSON.stringify(body) }),
  enableWired: (body: WiredShareActivationRequest) =>
    request<WiredShareState>('/wired/enable', { method: 'POST', body: JSON.stringify(body) }),
  disableWired: (body: WiredShareActivationRequest) =>
    request<WiredShareState>('/wired/disable', { method: 'POST', body: JSON.stringify(body) }),
  confirmWired: () => request<WiredShareState>('/wired/confirm', { method: 'POST' }),
  deleteWired: () => request<void>('/wired', { method: 'DELETE' }),

  /** Ask the wired share's DHCP server to forget one lease, keyed by MAC alone. */
  releaseWiredLease: (macAddress: string) =>
    request<void>(`/wired/clients/${encodeURIComponent(macAddress)}`, { method: 'DELETE' }),

  // Config export/import. The download route is deliberately NOT fetched here —
  // it is a plain navigation so the browser's own save-file behaviour handles
  // `Content-Disposition`, rather than the app building a blob and an object URL.
  exportConfig: () => request<SentryConfig>('/config'),
  importConfig: (body: ConfigImportRequest) =>
    request<ConfigImportResult>('/config', { method: 'POST', body: JSON.stringify(body) }),
}
