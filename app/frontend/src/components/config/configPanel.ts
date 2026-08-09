import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import type { ConfigImportResult } from '../../api/client.js'
import { baseButton } from '../base/baseButton.js'
import { baseToggle } from '../base/baseToggle.js'
import { dataCell } from '../base/dataCell.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'
import {
  applyPendingImport,
  clearPendingImport,
  configStore,
  exportDeviceCount,
  loadPreview,
  pendingDeviceCount,
  pendingHasHotspot,
  stagePickedFile,
  type ConfigStoreState,
} from '../../state/configStore.js'
import { configImportReport } from './configImportReport.js'

/**
 * Download this Sentry's configuration, or apply one exported from another.
 *
 * The reason this exists: standing up a second Pi otherwise means retyping
 * every device's name, port, antenna and visibility by hand and getting all
 * of them right.
 *
 * Importing is deliberately two steps — pick a file, see what it contains,
 * then confirm. An import rewrites every device's configuration, which is
 * too much to happen as a side effect of a file-picker closing.
 *
 * Takes no props — it is rendered once near the app root and driven entirely
 * by `configStore`.
 */
export function configPanel(): Component<void> {
  const headingId = nextElementId('config-dialog-heading')

  const heading = sectionHeading({ level: 2, children: ['Configuration'] })
  heading.element.id = headingId
  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'Move a whole Sentry setup to another Pi. The file carries every configured device’s name, port, antenna, notes and visibility — never any password.',
  ])
  const headerBlock = el('div', { class: 'flex flex-col gap-2' }, [heading.element, introParagraph])

  const busyStatusRegion = el('p', { attrs: { role: 'status' }, class: 'sr-only' }, [])
  const errorAlertRegion = el('p', { attrs: { role: 'alert' }, class: 'sr-only' }, [])

  const errorNotice = noticeBox({ tone: 'danger', role: 'status', children: [] })

  // Export section.
  const exportHeadingId = nextElementId('config-export-heading')
  const exportHeading = sectionHeading({ level: 3, children: ['Export'] })
  exportHeading.element.id = exportHeadingId
  const configuredDevicesCell = dataCell({
    label: 'Configured devices',
    labelTag: 'dt',
    valueTag: 'dd',
    value: 0,
  })
  const hotspotIncludedCell = dataCell({
    label: 'Hotspot',
    labelTag: 'dt',
    valueTag: 'dd',
    value: 'Not set up',
  })
  const exportDetailsList = el('dl', { class: 'm-0 grid grid-cols-2 gap-x-6 gap-y-4' }, [
    configuredDevicesCell.element,
    hotspotIncludedCell.element,
  ])
  const downloadButton = baseButton({
    variant: 'ghost',
    onClick: () => void downloadConfig(),
    children: ['Download configuration'],
  })
  const exportSection = el(
    'section',
    { class: 'flex flex-col gap-3', attrs: { 'aria-labelledby': exportHeadingId } },
    [exportHeading.element, exportDetailsList, el('div', {}, [downloadButton.element])],
  )

  // Import section.
  const importHeadingId = nextElementId('config-import-heading')
  const importHeading = sectionHeading({ level: 3, children: ['Import'] })
  importHeading.element.id = importHeadingId

  const fileInput = el('input', {
    attrs: { type: 'file', accept: 'application/json,.json', 'aria-hidden': 'true', tabindex: -1 },
    class: 'sr-only',
    on: { change: (event) => void onFileChosen(event) },
  }) as HTMLInputElement

  const noPendingImportParagraph = el(
    'p',
    { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' },
    ['Choose a file exported from another Sentry. Nothing is applied until you confirm.'],
  )
  const pickFileButton = baseButton({
    variant: 'ghost',
    onClick: () => pickFile(),
    children: ['Choose a configuration file…'],
  })
  const noPendingImportBlock = el('div', { class: 'flex flex-col gap-3' }, [
    noPendingImportParagraph,
    el('div', {}, [pickFileButton.element]),
  ])

  const pendingFileNameStrong = el('strong', { class: 'font-semibold' }, [])
  const pendingCountTextNode = document.createTextNode('')
  const pendingSummaryParagraph = el('p', { class: 'm-0' }, [
    pendingFileNameStrong,
    ' contains ',
    pendingCountTextNode,
  ])
  const pendingHelpParagraph = el('p', { class: 'm-0 text-[11px]' }, [
    'Devices are matched by their identity, so a dongle that is not plugged into this Sentry yet is reported and skipped rather than failing the import.',
  ])
  const pendingNotice = noticeBox({
    tone: 'info',
    role: 'status',
    children: [
      el('div', { class: 'flex flex-col gap-2' }, [pendingSummaryParagraph, pendingHelpParagraph]),
    ],
  })

  const applyDevicesToggle = baseToggle({
    value: true,
    onChange: (value) => configStore.setState({ applyDevices: value }),
    label: 'Apply device settings',
    accessibleName: 'Apply device settings from the file',
  })
  const applyHotspotToggle = baseToggle({
    value: false,
    onChange: (value) => configStore.setState({ applyHotspot: value }),
    label: 'Apply hotspot settings',
    accessibleName: 'Apply hotspot settings from the file',
  })
  const hotspotPasswordParagraph = el('p', { class: '-mt-1 m-0 text-[11px] text-signal-muted' }, [
    'This writes the network’s settings but never starts it — you turn the hotspot on yourself. ' +
      'An exported file never contains the password; a file you wrote by hand may add a `passphrase` ' +
      'to set one. Without either, a Sentry with no password stored will refuse.',
  ])

  const applyImportButton = baseButton({
    variant: 'primary',
    onClick: () => void applyImportAction(),
    children: ['Apply this configuration'],
  })
  const cancelImportButton = baseButton({
    variant: 'ghost',
    onClick: () => clearPendingImport(),
    children: ['Cancel'],
  })
  const pendingActionsRow = el('div', { class: 'flex flex-wrap gap-2' }, [
    applyImportButton.element,
    cancelImportButton.element,
  ])

  const pendingImportBlock = el('div', { class: 'flex flex-col gap-3' }, [
    pendingNotice.element,
    applyDevicesToggle.element,
    applyHotspotToggle.element,
    hotspotPasswordParagraph,
    pendingActionsRow,
  ])

  const importReportSlot = el('div')

  const importSection = el(
    'section',
    { class: 'flex flex-col gap-3', attrs: { 'aria-labelledby': importHeadingId } },
    [importHeading.element, fileInput, noPendingImportBlock, pendingImportBlock, importReportSlot],
  )

  const panelRoot = el(
    'section',
    { class: 'flex flex-col gap-6', attrs: { 'aria-labelledby': headingId } },
    [
      headerBlock,
      busyStatusRegion,
      errorAlertRegion,
      errorNotice.element,
      // Export and import are grouped and spaced further apart than the panel's
      // own `gap-6`. At the same gap, IMPORT sat as close to the export button
      // as that button did to its own caption, so the two halves read as one
      // run of controls rather than two things you choose between.
      el('div', { class: 'flex flex-col gap-10' }, [exportSection, importSection]),
    ],
  )

  let importReport: Component<{ result: ConfigImportResult }> | null = null

  /**
   * Save the configuration as a file.
   *
   * Fetches through the authenticated API client and builds the file
   * locally, rather than linking straight at `/api/config/download`. A plain
   * navigation cannot set an `Authorization` header, so a link would 401 the
   * moment an operator sets a token — and the alternative, putting the token
   * in the URL as `EventSource` has to, would write a credential into
   * browser history and the access log. `EventSource` has no choice; this
   * does.
   */
  async function downloadConfig(): Promise<void> {
    await loadPreview()
    const preview = configStore.state.preview
    if (preview === null) {
      return
    }
    const blob = new Blob([JSON.stringify(preview, null, 2) + '\n'], { type: 'application/json' })
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = 'sentry-config.json'
    link.click()
    URL.revokeObjectURL(objectUrl)
  }

  function pickFile(): void {
    fileInput.click()
  }

  async function onFileChosen(event: Event): Promise<void> {
    const input = event.target
    if (!(input instanceof HTMLInputElement)) {
      return
    }
    const file = input.files?.[0]
    if (!file) {
      return
    }
    stagePickedFile(file.name, await file.text())
    // Clear the input so picking the *same* file again still fires `change`.
    input.value = ''
  }

  async function applyImportAction(): Promise<void> {
    await applyPendingImport()
  }

  function render(state: ConfigStoreState): void {
    const isBusy = state.phase === 'importing'

    setText(busyStatusRegion, isBusy ? 'Importing configuration.' : '')
    setText(errorAlertRegion, state.errorMessage ?? '')

    setVisible(errorNotice.element, state.errorMessage !== null)
    if (state.errorMessage !== null) {
      errorNotice.update({ tone: 'danger', role: 'status', children: [state.errorMessage] })
    }

    downloadButton.update({
      variant: 'ghost',
      disabled: isBusy,
      onClick: () => void downloadConfig(),
      children: ['Download configuration'],
    })
    configuredDevicesCell.update({
      label: 'Configured devices',
      labelTag: 'dt',
      valueTag: 'dd',
      value: exportDeviceCount(state),
    })
    hotspotIncludedCell.update({
      label: 'Hotspot',
      labelTag: 'dt',
      valueTag: 'dd',
      value: state.preview?.hotspot ? 'Included' : 'Not set up',
    })

    pickFileButton.update({
      variant: 'ghost',
      disabled: isBusy,
      onClick: () => pickFile(),
      children: ['Choose a configuration file…'],
    })

    const hasPendingImport = state.pendingImport !== null
    setVisible(noPendingImportBlock, !hasPendingImport)
    setVisible(pendingImportBlock, hasPendingImport)

    if (hasPendingImport) {
      setText(pendingFileNameStrong, state.pendingFileName ?? '')
      const count = pendingDeviceCount(state)
      const hotspotSuffix = pendingHasHotspot(state) ? ' and a hotspot configuration' : ''
      pendingCountTextNode.data = `${count} device ${count === 1 ? 'entry' : 'entries'}${hotspotSuffix}.`

      applyDevicesToggle.update({
        value: state.applyDevices,
        onChange: (value) => configStore.setState({ applyDevices: value }),
        label: 'Apply device settings',
        accessibleName: 'Apply device settings from the file',
        disabled: isBusy,
      })

      const showHotspotToggle = pendingHasHotspot(state)
      setVisible(applyHotspotToggle.element, showHotspotToggle)
      setVisible(hotspotPasswordParagraph, showHotspotToggle)
      if (showHotspotToggle) {
        applyHotspotToggle.update({
          value: state.applyHotspot,
          onChange: (value) => configStore.setState({ applyHotspot: value }),
          label: 'Apply hotspot settings',
          accessibleName: 'Apply hotspot settings from the file',
          disabled: isBusy,
        })
      }

      applyImportButton.update({
        variant: 'primary',
        disabled: isBusy || (!state.applyDevices && !state.applyHotspot),
        onClick: () => void applyImportAction(),
        children: [isBusy ? 'Importing…' : 'Apply this configuration'],
      })
      cancelImportButton.update({
        variant: 'ghost',
        disabled: isBusy,
        onClick: () => clearPendingImport(),
        children: ['Cancel'],
      })
    }

    setVisible(importReportSlot, state.lastResult !== null)
    if (state.lastResult !== null) {
      if (!importReport) {
        importReport = configImportReport({ result: state.lastResult })
        importReportSlot.appendChild(importReport.element)
      } else {
        importReport.update({ result: state.lastResult })
      }
    }
  }

  const unsubscribe = watchStore(configStore, render)

  return {
    element: panelRoot,

    update(): void {
      // Store-driven; nothing to do for a prop this component does not take.
    },

    destroy(): void {
      unsubscribe()
      importReport?.destroy()
    },
  }
}
