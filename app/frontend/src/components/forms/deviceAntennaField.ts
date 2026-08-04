import type { Component } from '../../core/component.js'
import { baseField } from '../base/baseField.js'

/**
 * The antenna this device is fed by, as free text — "Discone, loft",
 * "1090 collinear on the chimney". Purely local documentation: it is never
 * published in `GET /api/v1/sdrs`, so it can name a location as loosely or
 * as precisely as the operator likes.
 *
 * Optional, so an empty value is valid and commits as `""` (which clears any
 * previous entry) rather than being rejected. Validates on blur, matching
 * `DeviceNameField` — a half-typed antenna is not an error — and returns
 * focus to the field when the one rule it does have (120 characters) fails.
 */
export interface DeviceAntennaFieldProps {
  value: string
  onChange: (value: string) => void
  onCommit: (antenna: string) => void
  serverError?: string | null
  disabled?: boolean
  /** Extra class(es) applied once to the field's root, e.g. a fixed width for a grid track. */
  className?: string
}

/** Mirrors `DevicePatch.antenna`'s `max_length`; the server re-validates regardless. */
const MAX_ANTENNA_LENGTH = 120

/** Builds a `DeviceAntennaField`. `update` mutates the same input in place — the caret is never disturbed. */
export function deviceAntennaField(
  props: DeviceAntennaFieldProps,
): Component<DeviceAntennaFieldProps> {
  let currentProps = props
  let clientError: string | null = null

  function validateAndCommit(): void {
    const trimmed = currentProps.value.trim()
    if (trimmed.length > MAX_ANTENNA_LENGTH) {
      clientError = `Antenna must be ${MAX_ANTENNA_LENGTH} characters or fewer.`
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
      label: 'Antenna',
      value: currentProps.value,
      onChange: (value) => currentProps.onChange(value),
      error: clientError ?? currentProps.serverError ?? null,
      disabled: currentProps.disabled ?? false,
      onBlur: validateAndCommit,
    })
  }

  const field = baseField({
    label: 'Antenna',
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
