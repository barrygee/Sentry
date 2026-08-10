import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { SentryConfig } from '../../api/client.js'
import { applyEditedConfig } from '../../state/configStore.js'
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

  const introParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'This Sentry’s configuration as it stands. Edit it and press Save to apply it — the same as importing a file with these contents.',
  ])

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
      'This replaces the stored configuration for the devices it names. There is no undo — Revert only discards unsaved text.',
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
    [heading.element, introParagraph, configField.element, buttonRow, confirmDialog.element],
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

    // The controls appear only once something is unsaved, so a section at rest
    // carries no buttons that would do nothing.
    setVisible(buttonRow, hasLocalEdits || nextProps.busy)
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
        ? 'This will apply 1 device from the configuration below.'
        : `This will apply ${devices} devices from the configuration below.`,
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
      confirmApplyButton.destroy()
      confirmCancelButton.destroy()
      confirmDialog.destroy()
    },
  }
}
