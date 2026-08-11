import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import type { ConfigImportResult } from '../../api/client.js'
import { baseButton } from '../base/baseButton.js'
import { baseToggle } from '../base/baseToggle.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { disclosureSection } from '../base/disclosureSection.js'

import { configEditorSection } from './configEditorSection.js'
import {
  applyPendingImport,
  clearPendingImport,
  configStore,
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

  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'Export this Sentry’s configuration, then import it into another Sentry. It carries each device’s name, port, antenna, notes and visibility. Passwords are not exported.',
  ])
  // No top padding of its own: every settings section is a card now, and the
  // card's own `p-card` is what separates a heading from the box above it. An
  // extra `pt-6` here — added when these sections shared one surface — left
  // Configuration sitting lower inside its box than the other two.
  const headerBlock = el('div', { class: 'flex flex-col gap-2' }, [introParagraph])

  const busyStatusRegion = el('p', { attrs: { role: 'status' }, class: 'sr-only' }, [])
  const errorAlertRegion = el('p', { attrs: { role: 'alert' }, class: 'sr-only' }, [])

  const errorNotice = noticeBox({ tone: 'danger', role: 'status', children: [] })

  // Import.
  const fileInput = el('input', {
    attrs: { type: 'file', accept: 'application/json,.json', 'aria-hidden': 'true', tabindex: -1 },
    class: 'sr-only',
    on: { change: (event) => void onFileChosen(event) },
  }) as HTMLInputElement

  const pickFileButton = baseButton({
    variant: 'ghost',
    onClick: () => pickFile(),
    children: ['Import'],
  })
  // `contents`, so that hiding it while a file is staged removes it from the
  // row rather than leaving a gap where a button was.
  const noPendingImportBlock = el('div', { class: 'contents' }, [pickFileButton.element])

  const editorSection = configEditorSection({
    preview: null,
    busy: false,
    extraControls: [noPendingImportBlock, fileInput],
  })

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

  // `contents` for the same reason as the sign-out wrapper: empty, a plain div
  // is still a flex item and still earns the section's gap, leaving the card
  // padded at the bottom by a row with nothing in it.
  const importReportSlot = el('div', { class: 'contents' })

  // What is left of the import flow once its button moved up beside Export: the
  // staged-file confirmation and the report of what an import did.
  // `contents`: with nothing staged and no report to show, a plain wrapper is
  // still a flex item with no height, and still earns the panel's `gap-10` —
  // which is the dead space at the bottom of the Configuration card.
  const importSection = el('div', { class: 'contents' }, [pendingImportBlock, importReportSlot])

  const disclosure = disclosureSection({
    label: ['Configuration'],
    headingLevel: 2,
    headingId,
    tone: 'panel',
    defaultOpen: true,
    isBoxTitle: true,
    bodyClass: 'flex flex-col gap-6',
    children: [
      headerBlock,
      busyStatusRegion,
      errorAlertRegion,
      errorNotice.element,
      // Export and import are grouped and spaced further apart than the panel's
      // own `gap-6`. At the same gap, IMPORT sat as close to the export button
      // as that button did to its own caption, so the two halves read as one
      // run of controls rather than two things you choose between.
      el('div', { class: 'flex flex-col gap-10' }, [editorSection.element, importSection]),
    ],
  })

  const panelRoot = el(
    'section',
    {
      class: 'flex flex-col bg-ground-panel p-card',
      attrs: { 'aria-labelledby': headingId },
    },
    [disclosure.element],
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

    editorSection.update({ preview: state.preview, busy: isBusy })

    setText(busyStatusRegion, isBusy ? 'Importing configuration.' : '')
    setText(errorAlertRegion, state.errorMessage ?? '')

    setVisible(errorNotice.element, state.errorMessage !== null)
    if (state.errorMessage !== null) {
      errorNotice.update({ tone: 'danger', role: 'status', children: [state.errorMessage] })
    }

    pickFileButton.update({
      variant: 'ghost',
      disabled: isBusy,
      onClick: () => pickFile(),
      children: ['Import'],
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
      disclosure.destroy()
      editorSection.destroy()
      importReport?.destroy()
    },
  }
}
