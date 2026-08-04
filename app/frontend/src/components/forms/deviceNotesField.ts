import type { Component } from '../../core/component.js'
import { baseField } from '../base/baseField.js'

/**
 * The operator's notes about this device — siting problems, whose dongle it
 * is, what still needs fixing. Published to Sentinel in `GET /api/v1/sdrs`
 * along with every other device field.
 *
 * Multi-line and optional: an empty value commits as `""`, clearing the note.
 * Commits on blur like every other field on the card.
 */
export interface DeviceNotesFieldProps {
  value: string
  onChange: (value: string) => void
  onCommit: (notes: string) => void
  serverError?: string | null
  disabled?: boolean
}

/** Mirrors `DevicePatch.notes`'s `max_length`; the server re-validates regardless. */
const MAX_NOTES_LENGTH = 2000

/** Builds a `DeviceNotesField`. `update` mutates the same textarea in place — the caret is never disturbed. */
export function deviceNotesField(props: DeviceNotesFieldProps): Component<DeviceNotesFieldProps> {
  let currentProps = props
  let clientError: string | null = null

  function validateAndCommit(): void {
    const trimmed = currentProps.value.trim()
    if (trimmed.length > MAX_NOTES_LENGTH) {
      clientError = `Notes must be ${MAX_NOTES_LENGTH} characters or fewer.`
      renderField()
      field.focus()
      return
    }
    clientError = null
    renderField()
    currentProps.onCommit(trimmed)
  }

  function renderField(): void {
    field.update({
      label: 'Notes',
      value: currentProps.value,
      multiline: true,
      rows: 3,
      onChange: (value) => currentProps.onChange(value),
      error: clientError ?? currentProps.serverError ?? null,
      disabled: currentProps.disabled ?? false,
      onBlur: validateAndCommit,
    })
  }

  const field = baseField({
    label: 'Notes',
    value: props.value,
    multiline: true,
    rows: 3,
    onChange: (value) => currentProps.onChange(value),
    error: clientError ?? props.serverError ?? null,
    disabled: props.disabled ?? false,
    onBlur: validateAndCommit,
  })

  return {
    element: field.element,

    update(nextProps): void {
      currentProps = nextProps
      renderField()
    },

    destroy(): void {
      field.destroy()
    },
  }
}
