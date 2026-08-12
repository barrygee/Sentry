import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { DeviceStatus } from '../../api/client.js'
import { deleteDevice, patchDevice, sdrsStore } from '../../state/sdrsStore.js'
import { baseButton } from '../base/baseButton.js'
import { baseToggle } from '../base/baseToggle.js'
import { confirmIconAction } from '../base/confirmIconAction.js'
import type { ConfirmIconActionProps } from '../base/confirmIconAction.js'
import { dataCell } from '../base/dataCell.js'
import { monoValue } from '../base/monoValue.js'
import { deviceAntennaField } from '../forms/deviceAntennaField.js'
import { deviceNameField } from '../forms/deviceNameField.js'
import { deviceNotesField } from '../forms/deviceNotesField.js'
import { portAssignmentField } from '../forms/portAssignmentField.js'

import { deviceAbsentNotice } from './deviceAbsentNotice.js'
import { deviceStatusBadge } from './deviceStatusBadge.js'
import { deviceVisibilityToggle } from './deviceVisibilityToggle.js'
import { disclosureSection } from '../base/disclosureSection.js'
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

/**
 * "SDR enabled" while it is on, "Enable SDR" while it is off.
 *
 * Not symmetrical, deliberately. An on switch labelled "Disable SDR" reads as a
 * claim about the current state to anyone scanning the card — the opposite of
 * the truth — so the on state describes itself. An off switch has the opposite
 * problem: "SDR enabled" beside an off switch is a flat contradiction, and the
 * useful thing to say there is what turning it on would do.
 *
 * The accessible name carries the device with it either way, since a screen
 * reader user meets these labels one at a time with no card to look at.
 */
function enabledToggleLabel(device: DeviceStatus): string {
  return device.enabled ? 'SDR enabled' : 'Enable SDR'
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

  // Whether the operator has touched this card since it was last in step with
  // the server. Tracked explicitly rather than inferred from "do the drafts
  // differ from the device", because that comparison cannot tell an edit made
  // here from a change made elsewhere — and answering "dirty" to the second
  // would freeze the card against every rename arriving from Sentinel.
  let hasLocalEdits = false

  function noteLocalEdit(): void {
    hasLocalEdits = true
  }

  function currentDevice(): DeviceStatus {
    return currentProps.device
  }

  // Blur reports a *validated* value; it no longer writes it. Each of these
  // records the cleaned-up draft and nothing more — the network write happens
  // once, when Save is pressed, so a half-finished card is never persisted and
  // tabbing between fields costs no requests.
  function commitName(name: string): void {
    noteLocalEdit()
    nameDraft = name
    validatedNameDraft = name
    render()
  }

  function commitPort(port: number): void {
    noteLocalEdit()
    portDraft = port
    validatedPortDraft = port
    render()
  }

  function commitAntenna(antenna: string): void {
    noteLocalEdit()
    antennaDraft = antenna
    render()
  }

  function commitNotes(notes: string): void {
    noteLocalEdit()
    notesDraft = notes
    render()
  }

  /** Whether any draft differs from what the server currently holds. */
  function draftsDifferFromDevice(): boolean {
    const device = currentDevice()
    return (
      nameDraft !== device.name ||
      portDraft !== (device.output?.iq_port ?? null) ||
      antennaDraft !== device.antenna ||
      notesDraft !== device.notes
    )
  }

  /** Whether this operator has changes here that the server has not got yet. */
  function hasUnsavedChanges(): boolean {
    return hasLocalEdits && draftsDifferFromDevice()
  }

  /** True while this card's own PATCH is in flight. */
  function isSaving(): boolean {
    return sdrsStore.state.pendingPatchesByDeviceId[currentDevice().device_id] !== undefined
  }

  /**
   * Whether Save can currently do anything useful.
   *
   * A device with no persisted row needs a *valid* name and port together —
   * the server has nothing to apply a partial patch to — so Save stays
   * unavailable until both have passed their own field validation.
   */
  function canSave(): boolean {
    if (!hasUnsavedChanges() || isSaving()) {
      return false
    }
    if (currentDevice().record_id === null) {
      return validatedNameDraft !== null && validatedPortDraft !== null
    }
    return true
  }

  function saveChanges(): void {
    if (!canSave()) {
      return
    }
    const device = currentDevice()

    if (device.record_id === null) {
      void patchDevice(device.device_id, {
        name: validatedNameDraft as string,
        output_port: validatedPortDraft as number,
      })
      return
    }

    // Only what actually changed: sending untouched fields back would make
    // every save a write of the whole row, and would clobber a field another
    // browser edited while this card sat open on stale values.
    const patch: Parameters<typeof patchDevice>[1] = {}
    if (nameDraft !== device.name) {
      patch.name = nameDraft
    }
    if (portDraft !== null && portDraft !== (device.output?.iq_port ?? null)) {
      patch.output_port = portDraft
    }
    if (antennaDraft !== device.antenna) {
      patch.antenna = antennaDraft
    }
    if (notesDraft !== device.notes) {
      patch.notes = notesDraft
    }
    void patchDevice(device.device_id, patch)
  }

  /** Throw the drafts away and show what the server holds. */
  function discardChanges(): void {
    const device = currentDevice()
    nameDraft = device.name
    portDraft = device.output?.iq_port ?? null
    antennaDraft = device.antenna
    notesDraft = device.notes
    validatedNameDraft = null
    validatedPortDraft = null
    hasLocalEdits = false
    render()
  }

  function commitEnabled(enabled: boolean): void {
    void patchDevice(currentDevice().device_id, { enabled })
  }

  function commitVisibility(visibility: 'public' | 'private'): void {
    void patchDevice(currentDevice().device_id, { visibility })
  }

  function requestSerialFlash(): void {
    currentProps.onRequestSerialFlash(currentDevice().device_id)
  }

  // --- Row 1 — identity and the one control that changes what the device is
  // doing right now. ---
  // Visible only while the card is collapsed. Open, the Name field a few rows
  // down already shows it and a second copy in the header is just two places
  // for one value to disagree; collapsed, it is the only thing that says which
  // dongle this card is. `group-open:` reads the `<details open>` state that
  // `DisclosureSection` puts the `group` class on. It stays an `h3` either way,
  // so the heading never leaves the accessibility tree.
  const headingElement = el(
    'h3',
    { class: 'm-0 font-sans text-[13px] font-semibold text-ink-primary group-open:sr-only' },
    [],
  )
  const statusBadge = deviceStatusBadge({
    state: props.device.state,
    reason: props.device.state_reason ?? null,
  })
  // Forgetting a device is only ever offered for one that is *absent* and
  // configured — the server refuses it outright (`409 device_present`) while
  // the hardware is plugged in, so showing the control on a present card would
  // be offering an action that cannot succeed.
  //
  // Inline arm-then-confirm rather than a modal: this is a small, local,
  // reversible-by-replugging action against one row, and a whole dialog for it
  // was enough ceremony that the entry point was never wired up at all.
  function forgetProps(): ConfirmIconActionProps {
    const label = currentDevice().name || currentDevice().device_id
    return {
      accessibleName: `Forget ${label}`,
      confirmAccessibleName: `Confirm forgetting ${label}`,
      cancelAccessibleName: `Cancel forgetting ${label}`,
      armedAnnouncement: `Confirm forgetting ${label}, or cancel. This discards its saved name, port and tuning defaults.`,
      cancelledAnnouncement: `Forgetting ${label} cancelled.`,
      // Reads the current device, not the one captured at construction: the
      // click lands long after this is built.
      onConfirm: () => {
        void deleteDevice(currentDevice().device_id)
      },
    }
  }

  const forgetAction = confirmIconAction(forgetProps())

  // The disclosure mounts its chevron here, so it sits on the status line
  // rather than taking a line of its own above it. `ml-auto` holds it at the
  // card's trailing edge however short the status text is.
  const chevronSlot = el('div', { class: 'ml-auto flex items-center' })

  // `w-full` is what makes the chevron's `ml-auto` mean anything: the header
  // column is `items-start`, so without it this row shrinks to its content and
  // there is no free space for the chevron to be pushed into — it sat against
  // the status badge instead of the card's edge.
  const identityRow = el('div', { class: 'flex w-full flex-wrap items-center gap-3' }, [
    headingElement,
    statusBadge.element,
    forgetAction.element,
    chevronSlot,
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
  // Enabled first: it is the switch that decides whether the dongle runs at
  // all, and visibility is a question about a device that is already running.
  const togglesRow = el('div', { class: 'flex flex-wrap items-center gap-x-10 gap-y-3' }, [
    enabledToggle.element,
    visibilityToggle.element,
  ])

  // A click on a toggle inside a `<summary>` also reaches the summary and
  // collapses the card. Stopping it here keeps the switches usable in place —
  // without this, turning an SDR off would fold the card shut underneath the
  // finger that did it.
  togglesRow.addEventListener('click', (event) => event.stopPropagation())

  // Status on one line, the switches left-aligned on the next. Side by side
  // they were pushed to the far right of the card, a long way from the state
  // they act on; stacked, both start at the same left edge as everything else
  // in the card.
  const headerRow = el('div', { class: 'flex flex-1 flex-col items-start gap-4' }, [
    identityRow,
    togglesRow,
  ])

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
      'Configuring a new device needs both a valid name and a valid output port — Save becomes available once both have been entered.',
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

  // --- Save ---
  // One Save for the whole card rather than one per field: the four editable
  // fields describe a single device, an operator changing two of them means one
  // change, and a first configuration *must* send name and port together
  // anyway. The row is only rendered when something is actually unsaved, so a
  // card at rest carries no controls that would do nothing.
  const unsavedLabel = el('span', { class: 'text-[12.5px] leading-[1.55] text-signal-muted' }, [
    'Unsaved changes',
  ])
  const saveButton = baseButton({
    variant: 'primary',
    onClick: saveChanges,
    children: ['Save changes'],
  })
  const discardButton = baseButton({
    variant: 'ghost',
    onClick: discardChanges,
    children: ['Discard'],
  })
  // `role="status"` so the row's arrival is announced rather than only seen —
  // a keyboard operator who has tabbed past the fields gets told there is
  // something left to do.
  const saveRow = el(
    'div',
    {
      attrs: { role: 'status' },
      class: 'flex flex-wrap items-center gap-x-4 gap-y-3',
    },
    [saveButton.element, discardButton.element, unsavedLabel],
  )

  // Collapsible, open by default: a rack of eight dongles is a lot of page,
  // and folding the ones already configured is the point. The header stays
  // visible when shut, so state and the two switches remain reachable.
  const disclosure = disclosureSection({
    label: [],
    summaryContent: [headerRow],
    defaultOpen: false,
    persistKey: `device.${props.device.device_id}`,
    isBoxTitle: true,
    chevronSlot,
    // Before the disclosure, the card was a `flex flex-col gap-6`, so its header
    // sat 24px above the first row; a `<summary>` sits flush against the body,
    // so that gap is restored here.
    bodyClass: 'flex flex-col gap-6 pt-6',
    children: [
      needsIdNotice.element,
      absentNotice.element,
      fieldsGrid,
      antennaField.element,
      notesField.element,
      saveRow,
    ],
  })

  const article = el(
    'article',
    {
      attrs: { id: `device-card-${props.device.device_id}`, tabindex: -1 },
      class: 'flex flex-col rounded-rack bg-ground-panel p-card outline-none',
    },
    [disclosure.element],
  )

  function render(): void {
    const device = currentDevice()

    // A save that landed puts the card back in step: the device now carries
    // what was typed, so the edits are no longer local and the row can go.
    if (hasLocalEdits && !isSaving() && !draftsDifferFromDevice()) {
      hasLocalEdits = false
    }

    // Never re-sync a draft over an unsaved change.
    //
    // `health` arrives every 5 seconds, and each one re-renders every card. The
    // earlier guard was "is anything inside this card focused", which held only
    // while a field had the caret — enough when blur saved immediately, and
    // wrong now that saving is a separate press: tab out of a field and the
    // next tick would restore the stored value before Save was ever reached.
    //
    // Dirtiness is the honest test. A card with no edits has drafts equal to
    // the device already, so syncing it is a no-op either way; a card with
    // edits keeps them until the operator saves or discards. That is the
    // deliberate trade recorded in ADR-0012 — local drafts win over a concurrent
    // change from elsewhere, silently, because a conflict notice on a
    // single-operator device would be noise. That ADR also lists what should
    // trigger revisiting it, the first being any second writer.
    if (!hasUnsavedChanges() && !isSaving()) {
      nameDraft = device.name
      portDraft = device.output?.iq_port ?? null
      antennaDraft = device.antenna
      notesDraft = device.notes
    }

    setText(headingElement, device.name || device.device_id)
    statusBadge.update({ state: device.state, reason: device.state_reason ?? null })

    setVisible(togglesRow, device.record_id !== null)
    setVisible(forgetAction.element, !device.present && device.record_id !== null)
    forgetAction.update(forgetProps())
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
        noteLocalEdit()
        nameDraft = value
        render()
      },
      onCommit: commitName,
    })

    setVisible(portField.element, isEditable)
    portField.update({
      value: portDraft,
      onChange: (value) => {
        noteLocalEdit()
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
        noteLocalEdit()
        antennaDraft = value
        render()
      },
      onCommit: commitAntenna,
    })
    setVisible(notesField.element, showAntennaAndNotes)
    notesField.update({
      value: notesDraft,
      onChange: (value) => {
        noteLocalEdit()
        notesDraft = value
        render()
      },
      onCommit: commitNotes,
    })

    // Keyed on the operator having text edits here, never on "a patch is in
    // flight": the enabled and visibility switches patch immediately and have
    // nothing to save, so keying on the request made the row flash into view
    // and out again on every toggle.
    const saving = isSaving() && hasLocalEdits
    setVisible(saveRow, hasLocalEdits)
    saveButton.update({
      variant: 'primary',
      onClick: saveChanges,
      disabled: !canSave(),
      children: [saving ? 'Saving…' : 'Save changes'],
    })
    discardButton.update({
      variant: 'ghost',
      onClick: discardChanges,
      disabled: saving,
      children: ['Discard'],
    })
    setText(unsavedLabel, saving ? '' : 'Unsaved changes')
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
      forgetAction.destroy()
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
      saveButton.destroy()
      discardButton.destroy()
    },
  }
}
