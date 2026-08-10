import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { DeviceStatus } from '../../api/client.js'
import { patchDevice, sdrsStore } from '../../state/sdrsStore.js'
import { baseToggle } from '../base/baseToggle.js'
import { dataCell } from '../base/dataCell.js'
import { monoValue } from '../base/monoValue.js'
import { deviceAntennaField } from '../forms/deviceAntennaField.js'
import { deviceNameField } from '../forms/deviceNameField.js'
import { deviceNotesField } from '../forms/deviceNotesField.js'
import { portAssignmentField } from '../forms/portAssignmentField.js'

import { deviceAbsentNotice } from './deviceAbsentNotice.js'
import { deviceStatusBadge } from './deviceStatusBadge.js'
import { deviceVisibilityToggle } from './deviceVisibilityToggle.js'
import { needsIdentificationNotice } from './needsIdentificationNotice.js'

/**
 * One rack unit (architecture §9.5 layout): the composed, single-purpose
 * device presentation — it holds no formatting logic of its own, only
 * layout over `DeviceStatusBadge`, `DataCell`, `MonoValue` and the two
 * inline-editable form fields. This is the component `UsbTopologyTree`
 * moves focus to on Enter/Space (architecture §9.4).
 *
 * One device, in its own white box on the canvas: its status, its editable
 * fields and its read-only identity. There is no wrapping card and no title —
 * the boxes are the list.
 */
export interface SdrDeviceCardProps {
  device: DeviceStatus
  onRequestSerialFlash: (deviceId: string) => void
}

function identityModel(device: DeviceStatus): string {
  const manufacturer = device.usb?.manufacturer ?? device.usb_last_known?.manufacturer ?? null
  const product = device.usb?.product ?? device.usb_last_known?.product ?? null
  // Make and model as one string, or "Unknown" — many dongles report neither.
  return [manufacturer, product].filter(Boolean).join(' ') || 'Unknown'
}

function identitySerial(device: DeviceStatus): string | null {
  return device.usb?.serial ?? device.usb_last_known?.serial ?? null
}

function ownReservedPortsFor(device: DeviceStatus): number[] {
  return device.output ? [device.output.iq_port, device.output.control_port] : []
}

function enabledToggleLabel(device: DeviceStatus): string {
  return device.enabled ? 'Disable SDR' : 'Enable SDR'
}

/** Builds an `SdrDeviceCard`. `update` mutates the same DOM in place — the name, port, notes and antenna fields are edited inline, and rebuilding on update would drop the caret mid-keystroke. */
export function sdrDeviceCard(props: SdrDeviceCardProps): Component<SdrDeviceCardProps> {
  let currentProps = props

  // Local drafts, mirroring the retired component's refs. Only re-synced
  // from the device when no optimistic patch is outstanding for it (see
  // `render` below) — otherwise a slow PATCH response racing a fresh SSE
  // snapshot would stomp over what the operator is mid-typing.
  let nameDraft = props.device.name
  let portDraft = props.device.output?.iq_port ?? null
  let antennaDraft = props.device.antenna
  let notesDraft = props.device.notes

  // A device with no persisted record (`record_id === null`) has no row for
  // the server to apply a partial PATCH to, so `{name}` alone and
  // `{output_port}` alone are each individually rejected — there is no
  // "unconfigured but named" or "unconfigured but ported" state on the
  // server. The two fields must be validated locally and sent together in
  // one combined PATCH the first time; once a record exists, independent
  // field commits are correct (and cheaper) again.
  let validatedNameDraft: string | null = null
  let validatedPortDraft: number | null = null

  function currentDevice(): DeviceStatus {
    return currentProps.device
  }

  function commitName(name: string): void {
    if (currentDevice().record_id === null) {
      validatedNameDraft = name
      attemptFirstConfigurationCommit()
      return
    }
    void patchDevice(currentDevice().device_id, { name })
  }

  function commitPort(port: number): void {
    if (currentDevice().record_id === null) {
      validatedPortDraft = port
      attemptFirstConfigurationCommit()
      return
    }
    void patchDevice(currentDevice().device_id, { output_port: port })
  }

  function attemptFirstConfigurationCommit(): void {
    if (validatedNameDraft === null || validatedPortDraft === null) {
      return
    }
    void patchDevice(currentDevice().device_id, {
      name: validatedNameDraft,
      output_port: validatedPortDraft,
    })
  }

  function commitEnabled(enabled: boolean): void {
    void patchDevice(currentDevice().device_id, { enabled })
  }

  function commitVisibility(visibility: 'public' | 'private'): void {
    void patchDevice(currentDevice().device_id, { visibility })
  }

  // Antenna and notes are only ever offered on a device that already has a
  // persisted row, so — unlike name and port — they never need the combined
  // first-configuration PATCH above and can always be committed alone.
  function commitAntenna(antenna: string): void {
    void patchDevice(currentDevice().device_id, { antenna })
  }

  function commitNotes(notes: string): void {
    void patchDevice(currentDevice().device_id, { notes })
  }

  function requestSerialFlash(): void {
    currentProps.onRequestSerialFlash(currentDevice().device_id)
  }

  // --- Row 1 — identity and the one control that changes what the device is
  // doing right now. ---
  const headingElement = el('h3', { class: 'sr-only' }, [])
  const statusBadge = deviceStatusBadge({
    state: props.device.state,
    reason: props.device.state_reason ?? null,
  })
  const identityRow = el('div', { class: 'flex flex-wrap items-center gap-3' }, [
    headingElement,
    statusBadge.element,
  ])

  // Both switches sit together on the right: one controls whether the
  // device runs, the other whether anyone else is told about it.
  const visibilityToggle = deviceVisibilityToggle({
    device: props.device,
    onCommit: commitVisibility,
  })
  const enabledToggle = baseToggle({
    value: props.device.enabled,
    onChange: commitEnabled,
    label: enabledToggleLabel(props.device),
    accessibleName: `${enabledToggleLabel(props.device)} — ${props.device.name || props.device.device_id}`,
  })
  const togglesRow = el('div', { class: 'flex flex-wrap items-center gap-x-6 gap-y-2' }, [
    visibilityToggle.element,
    enabledToggle.element,
  ])

  const headerRow = el(
    'div',
    { class: 'flex flex-wrap items-center justify-between gap-x-6 gap-y-3' },
    [identityRow, togglesRow],
  )

  const needsIdNotice = needsIdentificationNotice({ onRequestSerialFlash: requestSerialFlash })
  const absentNotice = deviceAbsentNotice({
    lastTopologyPath: props.device.usb_last_known?.topology_path ?? null,
  })

  // Rows 2 and 3 share one grid, so their columns line up: "Output port"
  // sits above "Serial number", "Relay listens on" above "Center
  // frequency". As two independent flex rows each column landed wherever
  // its own content ended, and nothing aligned between them.
  //
  // Tracks are `max-content` rather than equal fractions — a model string
  // is far wider than a gain reading, and equal columns would have wrapped
  // the long one to make room for whitespace beside the short one. The
  // count steps down at narrower widths rather than overflowing.
  const nameField = deviceNameField({
    value: nameDraft,
    onChange: (value) => {
      nameDraft = value
    },
    onCommit: commitName,
    className: 'w-[160px]',
  })

  const portField = portAssignmentField({
    value: portDraft,
    onChange: (value) => {
      portDraft = value
    },
    onCommit: commitPort,
    constraints: sdrsStore.state.constraints,
    ownReservedPorts: ownReservedPortsFor(props.device),
  })

  const configureBothFieldsMessage = el(
    'p',
    { class: 'col-span-full m-0 text-[12.5px] leading-[1.55] text-signal-muted' },
    [
      'Configuring a new device needs both a valid name and a valid output port — nothing is saved until both fields have been entered.',
    ],
  )

  // `col-start-1` starts the read-only band on a fresh row instead of
  // flowing into whatever column the fields above left free.
  const modelDataCell = dataCell({
    label: 'Model',
    labelTag: 'dt',
    valueTag: 'dd',
    value: identityModel(props.device),
  })
  modelDataCell.element.classList.add('col-start-1')

  const serialMono = monoValue({ value: identitySerial(props.device) ?? '' })
  const serialDataCell = dataCell({
    label: 'Serial number',
    labelTag: 'dt',
    valueTag: 'dd',
    children: [serialMono.element],
  })

  const centerFrequencyMono = monoValue({ value: '', unit: 'MHz' })
  const centerFrequencyCell = dataCell({
    label: 'Center frequency',
    labelTag: 'dt',
    valueTag: 'dd',
    children: [centerFrequencyMono.element],
  })
  const rateMono = monoValue({ value: '', unit: 'kS/s' })
  const rateCell = dataCell({
    label: 'Rate',
    labelTag: 'dt',
    valueTag: 'dd',
    children: [rateMono.element],
  })
  // No unit when the tuner is in AGC: the value is a mode, not a
  // measurement, and "AGC dB" reads as nonsense.
  const gainMono = monoValue({ value: '' })
  const gainCell = dataCell({
    label: 'Gain',
    labelTag: 'dt',
    valueTag: 'dd',
    children: [gainMono.element],
  })

  const identityList = el('dl', { class: 'contents' }, [
    modelDataCell.element,
    serialDataCell.element,
    centerFrequencyCell.element,
    rateCell.element,
    gainCell.element,
  ])

  const fieldsGrid = el(
    'div',
    {
      class:
        'grid grid-cols-[repeat(2,max-content)] items-start gap-x-8 gap-y-5 sm:grid-cols-[repeat(3,max-content)] lg:grid-cols-[repeat(5,max-content)]',
    },
    [nameField.element, portField.element, configureBothFieldsMessage, identityList],
  )

  // Antenna and notes each get their own line below the aligned grid,
  // rather than a track inside it. Antenna follows the read-only band
  // (…rate, gain) so the tuning story reads in one block and the two
  // operator-written fields sit together underneath it; notes needs the
  // whole card width, which a `max-content` track cannot give it.
  // Only offered once a row exists — a lone antenna or notes PATCH on an
  // unconfigured device would be rejected, since a first configuration
  // must carry both name and port together.
  const antennaField = deviceAntennaField({
    value: antennaDraft,
    onChange: (value) => {
      antennaDraft = value
    },
    onCommit: commitAntenna,
    className: 'w-[240px]',
  })

  const notesField = deviceNotesField({
    value: notesDraft,
    onChange: (value) => {
      notesDraft = value
    },
    onCommit: commitNotes,
  })

  const article = el(
    'article',
    {
      attrs: { id: `device-card-${props.device.device_id}`, tabindex: -1 },
      class: 'flex flex-col gap-6 rounded-rack bg-ground-panel p-card outline-none',
    },
    [
      headerRow,
      needsIdNotice.element,
      absentNotice.element,
      fieldsGrid,
      antennaField.element,
      notesField.element,
    ],
  )

  function render(): void {
    const device = currentDevice()

    // Never re-sync a draft while the operator is working inside this card.
    //
    // The pending-patch check alone was not enough, and the gap it left was the
    // whole editing session: a patch only exists *after* a field commits on
    // blur, so from the first keystroke until the operator tabs away there is
    // nothing pending — and `health` arrives every 5 seconds. Each one reset
    // every draft to the stored value, wiped the input, and left a later blur
    // committing the empty draft it had just been given. Typing a note and
    // watching it vanish was the reported symptom; name, port and antenna were
    // going the same way.
    //
    // Focus is the right test rather than "is this field dirty": it is what
    // distinguishes "the operator is in the middle of something" from "this
    // card is idle and should follow the server".
    const isBeingEdited = article.contains(document.activeElement)
    if (
      !isBeingEdited &&
      sdrsStore.state.pendingPatchesByDeviceId[device.device_id] === undefined
    ) {
      nameDraft = device.name
      portDraft = device.output?.iq_port ?? null
      antennaDraft = device.antenna
      notesDraft = device.notes
    }

    setText(headingElement, device.name || device.device_id)
    statusBadge.update({ state: device.state, reason: device.state_reason ?? null })

    setVisible(togglesRow, device.record_id !== null)
    visibilityToggle.update({ device, onCommit: commitVisibility })
    enabledToggle.update({
      value: device.enabled,
      onChange: commitEnabled,
      label: enabledToggleLabel(device),
      accessibleName: `${enabledToggleLabel(device)} — ${device.name || device.device_id}`,
    })

    const isEditable = !device.needs_identification
    setVisible(needsIdNotice.element, device.needs_identification)
    needsIdNotice.update({ onRequestSerialFlash: requestSerialFlash })

    // `usb` and `usb_last_known` are mutually exclusive (architecture §7.2):
    // a present device reports the former, an absent configured one the
    // latter.
    setVisible(absentNotice.element, !device.needs_identification && !device.present)
    absentNotice.update({ lastTopologyPath: device.usb_last_known?.topology_path ?? null })

    setVisible(nameField.element, isEditable)
    nameField.update({
      value: nameDraft,
      onChange: (value) => {
        nameDraft = value
        render()
      },
      onCommit: commitName,
    })

    setVisible(portField.element, isEditable)
    portField.update({
      value: portDraft,
      onChange: (value) => {
        portDraft = value
        render()
      },
      onCommit: commitPort,
      constraints: sdrsStore.state.constraints,
      ownReservedPorts: ownReservedPortsFor(device),
    })

    const needsBothFieldsToConfigure =
      device.record_id === null && (validatedNameDraft === null || validatedPortDraft === null)
    setVisible(configureBothFieldsMessage, isEditable && needsBothFieldsToConfigure)

    modelDataCell.update({
      label: 'Model',
      labelTag: 'dt',
      valueTag: 'dd',
      value: identityModel(device),
    })

    const serial = identitySerial(device)
    setVisible(serialDataCell.element, serial !== null)
    serialMono.update({ value: serial ?? '' })

    const tuner = device.tuner
    const hasTuner = Boolean(tuner)
    setVisible(centerFrequencyCell.element, hasTuner)
    setVisible(rateCell.element, hasTuner)
    setVisible(gainCell.element, hasTuner)
    if (tuner) {
      centerFrequencyMono.update({ value: (tuner.center_hz / 1_000_000).toFixed(3), unit: 'MHz' })
      rateMono.update({ value: (tuner.sample_rate / 1_000).toFixed(0), unit: 'kS/s' })
      if (tuner.gain_auto) {
        gainMono.update({ value: 'AGC', unit: null })
      } else {
        gainMono.update({ value: tuner.gain_db.toFixed(1), unit: 'dB' })
      }
    }

    const showAntennaAndNotes = isEditable && device.record_id !== null
    setVisible(antennaField.element, showAntennaAndNotes)
    antennaField.update({
      value: antennaDraft,
      onChange: (value) => {
        antennaDraft = value
        render()
      },
      onCommit: commitAntenna,
    })
    setVisible(notesField.element, showAntennaAndNotes)
    notesField.update({
      value: notesDraft,
      onChange: (value) => {
        notesDraft = value
        render()
      },
      onCommit: commitNotes,
    })
  }

  render()

  return {
    element: article,

    update(nextProps): void {
      currentProps = nextProps
      render()
    },

    destroy(): void {
      statusBadge.destroy()
      visibilityToggle.destroy()
      enabledToggle.destroy()
      needsIdNotice.destroy()
      absentNotice.destroy()
      nameField.destroy()
      portField.destroy()
      modelDataCell.destroy()
      serialDataCell.destroy()
      serialMono.destroy()
      centerFrequencyCell.destroy()
      centerFrequencyMono.destroy()
      rateCell.destroy()
      rateMono.destroy()
      gainCell.destroy()
      gainMono.destroy()
      antennaField.destroy()
      notesField.destroy()
    },
  }
}
