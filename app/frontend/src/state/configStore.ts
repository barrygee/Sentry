import {
  apiClient,
  ApiError,
  type ConfigImportResult,
  type SentryConfig,
  type SentryConfigImport,
} from '../api/client.js'
import { liveAnnouncer } from '../core/liveAnnouncer.js'
import { createStore, type Store } from '../core/observable.js'
import * as sdrsStore from './sdrsStore.js'

/**
 * Export and import of a whole Sentry instance's configuration.
 *
 * The point is standing up a second Pi without retyping every device's name,
 * port, antenna and visibility by hand. Export from a working Sentry, import
 * into a fresh one.
 *
 * **No secret ever passes through here.** The exported file carries
 * `passphrase_set` and never a password, and the deploy-time gates
 * (`SENTRY_HOTSPOT_CONTROL_ENABLED`, since ADR-0013 an override rather than the
 * only way to set it) are `.env`-only by
 * design — see `schemas/config.py`.
 */

export type ConfigPhase = 'idle' | 'loading' | 'importing' | 'imported' | 'failed'

export interface ConfigStoreState {
  /** The instance's current configuration, for preview before download. */
  preview: SentryConfig | null
  /** The parsed contents of a file the operator picked, awaiting confirmation.
   *
   * The inbound shape, not the exported one: a hand-written provisioning file
   * may carry `hotspot.passphrase`, which an export never does. */
  pendingImport: SentryConfigImport | null
  /** The name of that file, so the UI can say what is about to be applied. */
  pendingFileName: string | null
  lastResult: ConfigImportResult | null
  phase: ConfigPhase
  errorMessage: string | null
  applyDevices: boolean
  applyHotspot: boolean
}

/** Export/import state for the whole Sentry instance's device and hotspot configuration. */
export const configStore: Store<ConfigStoreState> = createStore<ConfigStoreState>({
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
})

/** How many configured devices the current instance would export. */
export function exportDeviceCount(state: Readonly<ConfigStoreState>): number {
  return state.preview?.devices?.length ?? 0
}

/** How many device entries the picked file carries. */
export function pendingDeviceCount(state: Readonly<ConfigStoreState>): number {
  return state.pendingImport?.devices?.length ?? 0
}

/** Whether the picked file describes a hotspot at all. */
export function pendingHasHotspot(state: Readonly<ConfigStoreState>): boolean {
  return (state.pendingImport?.hotspot ?? null) !== null
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
    sdrsStore.setConstraints(devicesResponse.constraints)
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

/**
 * Discard a picked-but-unapplied import and clear the last result.
 *
 * Was `closeDialog`. Dropping the staged file matters more than it looks:
 * leaving the screen with one selected and returning later would show a file
 * primed to apply, chosen for reasons the operator no longer remembers, one
 * button away from rewriting every device's configuration.
 */
export function resetTransientState(): void {
  clearPendingImport()
  configStore.setState({ errorMessage: null, lastResult: null, phase: 'idle' })
}

/** Discards a picked import file without applying it. */
export function clearPendingImport(): void {
  configStore.setState({ pendingImport: null, pendingFileName: null })
}

/** Reloads the instance's current configuration for the export preview. */
export async function loadPreview(): Promise<void> {
  configStore.setState({ phase: 'loading' })
  try {
    configStore.setState({
      preview: await apiClient.exportConfig(),
      phase: 'idle',
      errorMessage: null,
    })
  } catch (error) {
    configStore.setState({
      errorMessage: describeError(error, 'Could not read this Sentry’s configuration.'),
      phase: 'failed',
    })
  }
}

/**
 * Parse a file the operator picked, without applying it.
 *
 * Deliberately two steps. An import rewrites every device's configuration,
 * so the operator sees what the file contains — and how many entries — and
 * confirms, rather than a file-picker doubling as the commit.
 */
export function stagePickedFile(fileName: string, contents: string): void {
  configStore.setState({ errorMessage: null, lastResult: null })
  let parsed: unknown
  try {
    parsed = JSON.parse(contents)
  } catch {
    configStore.setState({ errorMessage: `${fileName} is not valid JSON.`, phase: 'failed' })
    return
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    configStore.setState({
      errorMessage: `${fileName} does not look like a Sentry configuration file.`,
      phase: 'failed',
    })
    return
  }
  configStore.setState({
    pendingImport: parsed as SentryConfigImport,
    pendingFileName: fileName,
    phase: 'idle',
  })
}

/**
 * Apply configuration the operator edited by hand in the console.
 *
 * Reuses the import path rather than adding a second write route: this *is* an
 * import, just one whose source is a textarea instead of a file, and it should
 * obey the same section toggles and produce the same result summary.
 *
 * There is no separate confirm step, unlike the file picker. Picking a file is
 * a weak signal of intent — the operator may not remember what is in it — but
 * typing into the configuration and pressing Save is the confirmation.
 */
export async function applyEditedConfig(contents: string): Promise<boolean> {
  let parsed: unknown
  try {
    parsed = JSON.parse(contents)
  } catch (error) {
    configStore.setState({
      errorMessage: `That is not valid JSON: ${error instanceof Error ? error.message : 'it could not be parsed'}.`,
      phase: 'failed',
    })
    return false
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    configStore.setState({
      errorMessage: 'A Sentry configuration must be a JSON object.',
      phase: 'failed',
    })
    return false
  }
  configStore.setState({ pendingImport: parsed as SentryConfigImport, pendingFileName: null })
  return await applyPendingImport()
}

/** Sends the staged import to the server, applying whichever sections are enabled. */
export async function applyPendingImport(): Promise<boolean> {
  const { pendingImport, applyDevices, applyHotspot } = configStore.state
  if (pendingImport === null) {
    return false
  }
  configStore.setState({ phase: 'importing', errorMessage: null })
  try {
    const result = await apiClient.importConfig({
      config: pendingImport,
      apply_devices: applyDevices,
      apply_hotspot: applyHotspot,
    })
    configStore.setState({ lastResult: result, phase: 'imported' })
    clearPendingImport()
    liveAnnouncer().announcePolite(
      `Configuration imported: ${result.devices_applied} device${
        result.devices_applied === 1 ? '' : 's'
      } applied, ${result.devices_skipped} skipped, ${result.devices_failed} failed.`,
    )
    // The device cards themselves are driven by SSE and catch up on their
    // own. Port constraints are not — they are fetched once on mount — and
    // an import can consume several ports, so they are refreshed here or
    // the next inline port edit would validate against a stale set.
    void refreshPortConstraints()
    void loadPreview()
    return true
  } catch (error) {
    configStore.setState({
      errorMessage: describeError(error, 'The configuration could not be imported.'),
      phase: 'failed',
    })
    return false
  }
}
