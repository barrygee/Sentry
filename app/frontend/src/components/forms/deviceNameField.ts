import type { Component } from '../../core/component.js'
import { baseField } from '../base/baseField.js'

/**
 * The device's operator-facing name (architecture §7.5): 1-64 chars,
 * allow-listed charset, unique across the SDRs. Validates on blur, not
 * per keystroke — a partially typed name is not an error. On a validation
 * failure, focus is returned to the field rather than left wherever the
 * operator tabbed to, so a screen-reader user hears which field the error
 * belongs to.
 */
export interface DeviceNameFieldProps {
  value: string
  onChange: (value: string) => void
  onCommit: (name: string) => void
  serverError?: string | null
  disabled?: boolean
  /** Extra class(es) applied once to the field's root, e.g. a fixed width for a grid track. */
  className?: string
}

const NAME_PATTERN = /^[A-Za-z0-9 _.\-()/]+$/

/** Builds a `DeviceNameField`. `update` mutates the same input in place — the caret is never disturbed. */
export function deviceNameField(props: DeviceNameFieldProps): Component<DeviceNameFieldProps> {
  let currentProps = props
  let clientError: string | null = null

  function validateAndCommit(): void {
    const trimmed = currentProps.value.trim()
    if (trimmed.length === 0 || trimmed.length > 64) {
      clientError = 'Name must be 1-64 characters.'
      renderField()
      field.focus()
      return
    }
    if (!NAME_PATTERN.test(trimmed)) {
      clientError = 'Only letters, numbers, spaces and _ . - ( ) / are allowed.'
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
      label: 'Name',
      value: currentProps.value,
      onChange: (value) => currentProps.onChange(value),
      error: clientError ?? currentProps.serverError ?? null,
      disabled: currentProps.disabled ?? false,
      onBlur: validateAndCommit,
    })
  }

  const field = baseField({
    label: 'Name',
    value: props.value,
    onChange: (value) => currentProps.onChange(value),
    error: clientError ?? props.serverError ?? null,
    disabled: props.disabled ?? false,
    onBlur: validateAndCommit,
  })

  if (props.className) {
    field.element.classList.add(...props.className.split(' ').filter(Boolean))
  }

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
