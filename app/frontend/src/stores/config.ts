import { defineStore } from 'pinia'

import { apiClient, ApiError, type ConfigImportResult, type SentryConfig } from '@/api/client'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import { useSdrsStore } from '@/stores/sdrs'

/**
 * Export and import of a whole Sentry instance's configuration.
 *
 * The point is standing up a second Pi without retyping every device's name,
 * port, antenna and visibility by hand. Export from a working Sentry, import
 * into a fresh one.
 *
 * **No secret ever passes through here.** The exported file carries
 * `passphrase_set` and never a password, and the deploy-time gates
 * (`SENTRY_HOTSPOT_CONTROL_ENABLED`, `SENTRY_AUTH_TOKEN`) are `.env`-only by
 * design — see `schemas/config.py`.
 */

export type ConfigPhase = 'idle' | 'loading' | 'importing' | 'imported' | 'failed'

export interface ConfigStoreState {
  /** The instance's current configuration, for preview before download. */
  preview: SentryConfig | null
  /** The parsed contents of a file the operator picked, awaiting confirmation. */
  pendingImport: SentryConfig | null
  /** The name of that file, so the UI can say what is about to be applied. */
  pendingFileName: string | null
  lastResult: ConfigImportResult | null
  phase: ConfigPhase
  errorMessage: string | null
  applyDevices: boolean
  applyHotspot: boolean
  dialogOpen: boolean
}

/**
 * Re-read the port constraints into the SDR store after an import.
 *
 * Failure is swallowed: constraints are advisory (the server re-validates every
 * port on `PATCH` regardless), so a failed refresh must not turn a successful
 * import into a reported error.
 */
async function refreshPortConstraints(): Promise<void> {
  try {
    const devicesResponse = await apiClient.listDevices()
    useSdrsStore().setConstraints(devicesResponse.constraints)
  } catch {
    // Advisory only — the next PATCH is still validated server-side.
  }
}

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    switch (error.detail?.code) {
      case 'unsupported_config_version':
        return 'This file was written by a newer Sentry and cannot be read by this one.'
      default:
        return error.message || fallback
    }
  }
  return fallback
}

export const useConfigStore = defineStore('config', {
  state: (): ConfigStoreState => ({
    preview: null,
    pendingImport: null,
    pendingFileName: null,
    lastResult: null,
    phase: 'idle',
    errorMessage: null,
    applyDevices: true,
    // Off by default, matching the server: importing a hotspot changes which
    // network this Pi serves, and the file never carries a password to start
    // it with anyway.
    applyHotspot: false,
    dialogOpen: false,
  }),

  getters: {
    /** How many configured devices the current instance would export. */
    exportDeviceCount(state): number {
      return state.preview?.devices?.length ?? 0
    },
    /** How many device entries the picked file carries. */
    pendingDeviceCount(state): number {
      return state.pendingImport?.devices?.length ?? 0
    },
    /** Whether the picked file describes a hotspot at all. */
    pendingHasHotspot(state): boolean {
      return (state.pendingImport?.hotspot ?? null) !== null
    },
  },

  actions: {
    openDialog(): void {
      this.dialogOpen = true
      void this.loadPreview()
    },

    closeDialog(): void {
      this.dialogOpen = false
      this.clearPendingImport()
      this.errorMessage = null
      this.lastResult = null
      this.phase = 'idle'
    },

    clearPendingImport(): void {
      this.pendingImport = null
      this.pendingFileName = null
    },

    async loadPreview(): Promise<void> {
      this.phase = 'loading'
      try {
        this.preview = await apiClient.exportConfig()
        this.phase = 'idle'
        this.errorMessage = null
      } catch (error) {
        this.errorMessage = describeError(error, 'Could not read this Sentry’s configuration.')
        this.phase = 'failed'
      }
    },

    /**
     * Parse a file the operator picked, without applying it.
     *
     * Deliberately two steps. An import rewrites every device's configuration,
     * so the operator sees what the file contains — and how many entries — and
     * confirms, rather than a file-picker doubling as the commit.
     */
    stagePickedFile(fileName: string, contents: string): void {
      this.errorMessage = null
      this.lastResult = null
      let parsed: unknown
      try {
        parsed = JSON.parse(contents)
      } catch {
        this.errorMessage = `${fileName} is not valid JSON.`
        this.phase = 'failed'
        return
      }
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        this.errorMessage = `${fileName} does not look like a Sentry configuration file.`
        this.phase = 'failed'
        return
      }
      this.pendingImport = parsed as SentryConfig
      this.pendingFileName = fileName
      this.phase = 'idle'
    },

    async applyPendingImport(): Promise<boolean> {
      if (this.pendingImport === null) {
        return false
      }
      this.phase = 'importing'
      this.errorMessage = null
      try {
        const result = await apiClient.importConfig({
          config: this.pendingImport,
          apply_devices: this.applyDevices,
          apply_hotspot: this.applyHotspot,
        })
        this.lastResult = result
        this.phase = 'imported'
        this.clearPendingImport()
        useLiveAnnouncer().announcePolite(
          `Configuration imported: ${result.devices_applied} device${
            result.devices_applied === 1 ? '' : 's'
          } applied, ${result.devices_skipped} skipped, ${result.devices_failed} failed.`,
        )
        // The device cards themselves are driven by SSE and catch up on their
        // own. Port constraints are not — they are fetched once on mount — and
        // an import can consume several ports, so they are refreshed here or
        // the next inline port edit would validate against a stale set.
        void refreshPortConstraints()
        void this.loadPreview()
        return true
      } catch (error) {
        this.errorMessage = describeError(error, 'The configuration could not be imported.')
        this.phase = 'failed'
        return false
      }
    },
  },
})
