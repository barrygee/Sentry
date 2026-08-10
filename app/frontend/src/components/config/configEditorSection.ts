import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { SentryConfig } from '../../api/client.js'
import { applyEditedConfig, downloadConfig } from '../../state/configStore.js'
import { baseButton } from '../base/baseButton.js'
import { baseDialog } from '../base/baseDialog.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { sectionHeading } from '../base/sectionHeading.js'

/**
 * The whole configuration, shown as JSON and editable in place.
 *
 * Between Export and Import, and deliberately so: it is the same document both
 * of those move around, minus the round trip through a file. Renaming three
 * devices previously meant downloading, editing elsewhere, and uploading — or
 * three separate card edits.
 *
 * **This writes.** Saving is an import, applying the same section toggles and
 * producing the same summary, so a mistake here is as consequential as
 * uploading a bad file — it can rewrite every configured device at once, and
 * Revert only discards unsaved text rather than undoing a save. Save therefore
 * asks first, and the question names the number of devices about to be applied,
 * because "are you sure" tells an operator nothing they did not already know.
 *
 * The textarea follows the server until it is edited. After that the draft is
 * the operator's until they save or revert — the same rule the device cards
 * follow (ADR-0012), and for the same reason: a background refresh must never
 * discard typing.
 */
export interface ConfigEditorSectionProps {
  /** The instance's current configuration, or null before it has loaded. */
  preview: SentryConfig | null
  /** Whether an import is currently in flight. */
  busy: boolean
}

/**
 * Parse the draft, or `null` if it is not a configuration object.
 *
 * Used to decide whether Save can even ask for confirmation: a dialog offering
 * to apply unparseable text would be asking about something that cannot happen.
 */
function parseDraft(draft: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(draft)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return null
    }
    return parsed as Record<string, unknown>
  } catch {
    return null
  }
}

/** How many devices a parsed configuration carries, for the confirmation's copy. */
function deviceCount(parsed: Record<string, unknown> | null): number {
  const devices = parsed?.['devices']
  return Array.isArray(devices) ? devices.length : 0
}

/** Two-space JSON, matching what `Download configuration` produces. */
function formatConfig(preview: SentryConfig | null): string {
  return preview === null ? '' : JSON.stringify(preview, null, 2)
}

/** Builds a `ConfigEditorSection`. `update` mutates the same textarea in place. */
export function configEditorSection(
  props: ConfigEditorSectionProps,
): Component<ConfigEditorSectionProps> {
  const headingId = nextElementId('config-editor-heading')
  const heading = sectionHeading({ level: 3, size: 'small', children: ['View and edit'] })
  heading.element.id = headingId

  let draft = formatConfig(props.preview)
  let hasLocalEdits = false
  let confirmOpen = false
  // Collapsed by default, matching Sentinel's JSON editors: this is a bulk-edit
  // escape hatch, not the primary way to change a device, and eighteen rows of
  // JSON sitting open would dominate a panel most visits never use it for.
  let editorVisible = false

  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'This Sentry’s configuration as it stands. Edit it and press Save to apply it — the same as importing a file with these contents.',
  ])

  const INDENT = '  '

  /**
   * Indent with Tab instead of leaving the field.
   *
   * Sentinel's JSON editors do this and the reason is the same here: Tab is how
   * anyone edits nested JSON, and a textarea that instead moves focus to the
   * next control makes hand-editing genuinely unpleasant. Shift+Tab outdents,
   * and a multi-line selection shifts as a block.
   *
   * It does trap Tab, which normally costs keyboard users their way out of the
   * field. Escape is left alone and the field is reachable in both directions
   * by arrow keys from adjacent controls, and the editor is collapsed unless
   * deliberately opened — so the trap only exists while someone is editing.
   */
  function indentOnTab(event: KeyboardEvent): void {
    const textarea = event.target as HTMLTextAreaElement
    event.preventDefault()

    const { selectionStart, selectionEnd, value } = textarea
    const lineStart = value.lastIndexOf('\n', selectionStart - 1) + 1
    const spansLines = value.slice(selectionStart, selectionEnd).includes('\n')

    if (event.shiftKey) {
      const block = value.slice(lineStart, selectionEnd)
      const outdented = block.replace(/^( {1,2}|\t)/gm, '')
      textarea.value = value.slice(0, lineStart) + outdented + value.slice(selectionEnd)
      textarea.selectionStart = lineStart
      textarea.selectionEnd = lineStart + outdented.length
    } else if (spansLines) {
      const block = value.slice(lineStart, selectionEnd)
      const indented = block.replace(/^/gm, INDENT)
      textarea.value = value.slice(0, lineStart) + indented + value.slice(selectionEnd)
      textarea.selectionStart = selectionStart + INDENT.length
      textarea.selectionEnd = selectionEnd + (indented.length - block.length)
    } else {
      textarea.value = value.slice(0, selectionStart) + INDENT + value.slice(selectionEnd)
      textarea.selectionStart = selectionStart + INDENT.length
      textarea.selectionEnd = textarea.selectionStart
    }

    draft = textarea.value
    hasLocalEdits = true
    render(currentProps)
  }

  const configField = baseField({
    label: 'Configuration (JSON)',
    value: draft,
    multiline: true,
    rows: 18,
    onChange: (value) => {
      draft = value
      hasLocalEdits = true
      render(currentProps)
    },
  })

  /**
   * Ask before writing — unless the draft cannot be applied at all.
   *
   * Invalid JSON goes straight to `applyEditedConfig`, which records the parse
   * error and returns before any request. Confirming first would put a dialog
   * in front of an operation that was always going to fail.
   */
  function requestSave(): void {
    if (parseDraft(draft) === null) {
      void applyEditedConfig(draft)
      return
    }
    confirmOpen = true
    render(currentProps)
  }

  function closeConfirm(): void {
    confirmOpen = false
    render(currentProps)
  }

  function saveConfiguration(): void {
    confirmOpen = false
    void applyEditedConfig(draft).then((applied) => {
      if (applied) {
        // The store reloads the preview after a successful import, so dropping
        // the draft lets the textarea follow the server again — which also
        // shows what the server actually stored rather than what was typed.
        hasLocalEdits = false
        render(currentProps)
      }
    })
  }

  function revertToServerConfiguration(): void {
    draft = formatConfig(currentProps.preview)
    hasLocalEdits = false
    render(currentProps)
  }

  const saveButton = baseButton({
    variant: 'primary',
    onClick: requestSave,
    children: ['Apply changes'],
  })

  const revertButton = baseButton({
    variant: 'ghost',
    onClick: revertToServerConfiguration,
    children: ['Revert'],
  })

  // A footer bar on `ground-raised` with the commit action to the right,
  // matching Sentinel's settings pane: the same fill, the same accent button,
  // and the same place on screen, so the two apps do not each teach their own
  // location for "this is where you apply changes".
  //
  // Revert sits left of it rather than beside it — the destructive-adjacent
  // action should not be the one the pointer lands on by muscle memory.
  // `baseField` has no keydown seam, so the handler is attached to the textarea
  // it built. Reaching into another component's DOM is a compromise; adding a
  // key-handling prop to a field used by every form in the app, for one editor,
  // would be the larger one.
  const textarea = configField.element.querySelector('textarea')
  textarea?.setAttribute('spellcheck', 'false')
  textarea?.addEventListener('keydown', (event) => {
    if ((event as KeyboardEvent).key === 'Tab') {
      indentOnTab(event as KeyboardEvent)
    }
  })

  function toggleEditorVisible(): void {
    editorVisible = !editorVisible
    render(currentProps)
  }

  const visibilityButton = baseButton({
    variant: 'ghost',
    onClick: toggleEditorVisible,
    children: ['Edit'],
  })

  const exportButton = baseButton({
    variant: 'ghost',
    onClick: () => void downloadConfig(),
    children: ['Export'],
  })

  const disclosureRow = el('div', { class: 'flex flex-wrap items-center gap-2' }, [
    visibilityButton.element,
    exportButton.element,
  ])

  const buttonRow = el(
    'div',
    {
      attrs: { role: 'status' },
      class:
        'flex flex-wrap items-center justify-between gap-x-4 gap-y-3 bg-ground-raised px-4 py-3',
    },
    [revertButton.element, saveButton.element],
  )

  // --- Confirmation ---
  const confirmHeadingId = nextElementId('config-editor-confirm-heading')
  const confirmHeading = sectionHeading({ level: 2, children: ['Apply this configuration?'] })
  confirmHeading.element.id = confirmHeadingId

  const confirmConsequence = el('p', { class: 'm-0 text-[12.5px] leading-[1.55]' }, [])
  const confirmIrreversible = el(
    'p',
    { class: 'm-0 text-[12px] leading-[1.55] text-signal-muted' },
    [
      'There is no undo. Revert only discards unsaved text — it cannot bring back what this writes over.',
    ],
  )

  const confirmApplyButton = baseButton({
    variant: 'primary',
    onClick: saveConfiguration,
    children: ['Apply configuration'],
  })
  const confirmCancelButton = baseButton({
    variant: 'ghost',
    onClick: closeConfirm,
    children: ['Cancel'],
  })

  // Held once and passed back on every update: the dialog's body is stable, and
  // rebuilding it per render would replace the focused button mid-interaction.
  const confirmBody = el('div', { class: 'flex flex-col gap-4' }, [
    el('div', { class: 'flex flex-col gap-2' }, [
      confirmHeading.element,
      confirmConsequence,
      confirmIrreversible,
    ]),
    el('div', { class: 'flex flex-wrap items-center gap-2' }, [
      confirmApplyButton.element,
      confirmCancelButton.element,
    ]),
  ])

  const confirmDialog = baseDialog({
    open: false,
    labelledBy: confirmHeadingId,
    onClose: closeConfirm,
    children: [confirmBody],
  })

  const section = el(
    'section',
    { class: 'flex flex-col gap-3', attrs: { 'aria-labelledby': headingId } },
    // `confirmDialog.element` is deliberately absent: `baseDialog` teleports its
    // own overlay to `document.body` as `open` changes. Appending it here made
    // it a child of this section instead, so it rendered the moment Settings
    // opened and no amount of closing removed it.
    [heading.element, introParagraph, disclosureRow, configField.element, buttonRow],
  )

  let currentProps = props

  function render(nextProps: ConfigEditorSectionProps): void {
    currentProps = nextProps

    // Follow the server only while there is nothing unsaved here. Tracked with
    // an explicit flag rather than by comparing the draft to the formatted
    // preview: whitespace an operator added would otherwise read as an edit
    // forever, and a reformat by the server as an edit by them.
    if (!hasLocalEdits) {
      draft = formatConfig(nextProps.preview)
    }

    configField.update({
      label: 'Configuration (JSON)',
      value: draft,
      multiline: true,
      rows: 18,
      disabled: nextProps.busy,
      onChange: (value) => {
        draft = value
        hasLocalEdits = true
        render(currentProps)
      },
    })

    setVisible(configField.element, editorVisible)
    visibilityButton.update({
      variant: 'ghost',
      onClick: toggleEditorVisible,
      children: [editorVisible ? 'Hide' : 'Edit'],
    })
    exportButton.update({
      variant: 'ghost',
      onClick: () => void downloadConfig(),
      disabled: nextProps.busy,
      children: ['Export'],
    })

    // The commit controls appear only once something is unsaved, so a section
    // at rest carries no buttons that would do nothing. Hidden with the editor
    // too — unsaved text behind a collapsed panel would otherwise offer an
    // Apply whose subject is not on screen.
    setVisible(buttonRow, editorVisible && (hasLocalEdits || nextProps.busy))
    saveButton.update({
      variant: 'primary',
      onClick: requestSave,
      disabled: nextProps.busy || !hasLocalEdits,
      children: [nextProps.busy ? 'Applying…' : 'Apply changes'],
    })
    revertButton.update({
      variant: 'ghost',
      onClick: revertToServerConfiguration,
      disabled: nextProps.busy,
      children: ['Revert'],
    })

    // Counted from the draft, not the server's copy: the question is about what
    // is being applied, and those differ precisely when it matters most.
    const devices = deviceCount(parseDraft(draft))
    setText(
      confirmConsequence,
      devices === 1
        ? 'This writes 1 device to this Sentry, replacing the settings it currently holds for it.'
        : `This writes ${devices} devices to this Sentry, replacing the settings it currently holds for them.`,
    )
    confirmApplyButton.update({
      variant: 'primary',
      onClick: saveConfiguration,
      disabled: nextProps.busy,
      children: [nextProps.busy ? 'Applying…' : 'Apply configuration'],
    })
    confirmCancelButton.update({
      variant: 'ghost',
      onClick: closeConfirm,
      disabled: nextProps.busy,
      children: ['Cancel'],
    })
    confirmDialog.update({
      open: confirmOpen,
      labelledBy: confirmHeadingId,
      disableDismiss: nextProps.busy,
      onClose: closeConfirm,
      children: [confirmBody],
    })
  }

  render(props)

  return {
    element: section,

    update(nextProps): void {
      render(nextProps)
    },

    destroy(): void {
      heading.destroy()
      configField.destroy()
      saveButton.destroy()
      revertButton.destroy()
      confirmHeading.destroy()
      visibilityButton.destroy()
      exportButton.destroy()
      confirmApplyButton.destroy()
      confirmCancelButton.destroy()
      confirmDialog.destroy()
    },
  }
}
