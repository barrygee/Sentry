import { el } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { PortConstraints } from '../../api/client.js'
import { baseField } from '../base/baseField.js'
import { dataCell } from '../base/dataCell.js'
import { nextElementId } from '../base/idGenerator.js'
import { validatePortClientSide } from '../../utils/portValidation.js'

/**
 * The IQ output port `P` (architecture §7.5, §8) — `P+2` is implicitly
 * reserved. Validates on blur; a server `409 port_conflict`/`port_reserved_*`
 * renders in the same message slot as the client-side check (architecture
 * §9.4 forms rule).
 *
 * The relay's two ports are shown beside the input as a readout rather than
 * described in hint text underneath it: "the relay listens on P and P+2" made
 * the operator do the arithmetic, where `1250 / 1252` simply states it. It
 * tracks the *draft* value, so it updates as the field is typed into and
 * doubles as the preview of what is about to be assigned — which is why the
 * separate "Pending" jack pair this component used to render is gone.
 */
export interface PortAssignmentFieldProps {
  value: number | null
  onChange: (value: number | null) => void
  onCommit: (port: number) => void
  constraints: PortConstraints | null
  serverError?: string | null
  ownReservedPorts?: number[]
  disabled?: boolean
}

function portToText(value: number | null): string {
  return value === null ? '' : String(value)
}

/** `P / P+2`, from the draft so it tracks what is being typed, or an em dash while empty. */
function relayPortsSummary(value: number | null): string {
  return value === null ? '—' : `${value} / ${value + 2}`
}

/** Builds a `PortAssignmentField`. `update` mutates the same input/readout in place — the caret is never disturbed. */
export function portAssignmentField(
  props: PortAssignmentFieldProps,
): Component<PortAssignmentFieldProps> {
  let currentProps = props
  let clientError: string | null = null
  const relayPortsId = `${nextElementId('port-field')}-relay-ports`

  function handleTextChange(text: string): void {
    const parsed = Number.parseInt(text, 10)
    currentProps.onChange(Number.isNaN(parsed) ? null : parsed)
  }

  function validateAndCommit(): void {
    const value = currentProps.value
    if (value === null) {
      clientError = 'Port is required.'
      renderField()
      field.focus()
      return
    }
    if (currentProps.constraints) {
      const validationError = validatePortClientSide(
        value,
        currentProps.constraints,
        currentProps.ownReservedPorts ?? [],
      )
      if (validationError) {
        clientError = validationError
        renderField()
        field.focus()
        return
      }
    }
    clientError = null
    renderField()
    currentProps.onCommit(value)
  }

  function renderField(): void {
    field.update({
      label: 'Output port',
      value: portToText(currentProps.value),
      type: 'number',
      inputMode: 'numeric',
      onChange: handleTextChange,
      error: clientError ?? currentProps.serverError ?? null,
      disabled: currentProps.disabled ?? false,
      describedBy: relayPortsId,
      onBlur: validateAndCommit,
    })
    relayReadout.update({
      label: 'Relay listens on',
      value: relayPortsSummary(currentProps.value),
    })
  }

  const field = baseField({
    label: 'Output port',
    value: portToText(props.value),
    type: 'number',
    inputMode: 'numeric',
    onChange: handleTextChange,
    error: clientError ?? props.serverError ?? null,
    disabled: props.disabled ?? false,
    describedBy: relayPortsId,
    onBlur: validateAndCommit,
  })

  const relayReadout = dataCell({
    label: 'Relay listens on',
    value: relayPortsSummary(props.value),
  })
  relayReadout.element.id = relayPortsId

  // `display: contents` — the wrapper dissolves so the input and the readout
  // become separate items of the card's grid, landing in their own columns
  // above "Serial number" and "Center frequency". Wrapped in a box of their
  // own they would have shared a single column and aligned with neither.
  const root = el('div', { class: 'contents' }, [field.element, relayReadout.element])

  return {
    element: root,

    update(nextProps): void {
      currentProps = nextProps
      renderField()
    },

    destroy(): void {
      field.destroy()
      relayReadout.destroy()
    },
  }
}
