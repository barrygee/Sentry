import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { SentryConfig } from '../../api/client.js'
import { applyEditedConfig } from '../../state/configStore.js'
import { baseButton } from '../base/baseButton.js'
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
 * uploading a bad file. There is no separate confirm step, unlike the file
 * picker: choosing a file is a weak signal of intent, but typing into the
 * configuration and pressing Save is itself the confirmation.
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

  function saveConfiguration(): void {
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
    onClick: saveConfiguration,
    children: ['Save configuration'],
  })

  const revertButton = baseButton({
    variant: 'ghost',
    onClick: revertToServerConfiguration,
    children: ['Revert'],
  })

  const buttonRow = el(
    'div',
    { attrs: { role: 'status' }, class: 'flex flex-wrap items-center gap-x-4 gap-y-3' },
    [saveButton.element, revertButton.element],
  )

  const section = el(
    'section',
    { class: 'flex flex-col gap-3', attrs: { 'aria-labelledby': headingId } },
    [heading.element, introParagraph, configField.element, buttonRow],
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
      onClick: saveConfiguration,
      disabled: nextProps.busy || !hasLocalEdits,
      children: [nextProps.busy ? 'Saving…' : 'Save configuration'],
    })
    revertButton.update({
      variant: 'ghost',
      onClick: revertToServerConfiguration,
      disabled: nextProps.busy,
      children: ['Revert'],
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
    },
  }
}
