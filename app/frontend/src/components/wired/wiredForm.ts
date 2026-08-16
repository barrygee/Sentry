import { el, setVisible } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component, ComponentFactory } from '../../core/component.js'
import type { WiredInterface, WiredShareConfigRequest, WiredShareState } from '../../api/client.js'
import { baseField } from '../base/baseField.js'
import { baseSelect } from '../base/baseSelect.js'
import type { BaseSelectOption } from '../base/baseSelect.js'
import { baseToggle } from '../base/baseToggle.js'
import { nextElementId } from '../base/idGenerator.js'
import { validateGatewayCidrClientSide } from '../../utils/hotspotValidation.js'
import { wiredUplinkWarning } from './wiredUplinkWarning.js'

/**
 * The wired-sharing settings form.
 *
 * Much shorter than the hotspot's, and the difference is the whole point of the
 * feature: there is no network name to invent, no password to set and no radio
 * to tune. An Ethernet port either carries this Sentry's own connection or it
 * does not, and sharing it either happens or it does not. Two real decisions —
 * which port, and the address it hands out — plus the acknowledgement.
 *
 * Calls `onSubmit` with a complete `WiredShareConfigRequest` rather than
 * mutating any store directly, so the whole form is drivable from fixture props
 * alone.
 *
 * **The uplink warning is driven by the selected port**, not by whether the
 * server last complained. Choosing the port that carries this Sentry's own
 * connection surfaces the warning immediately, so the acknowledgement is a
 * decision rather than a reaction to a rejected save. On a one-port Pi that
 * warning is the normal case, not the exception.
 */
export interface WiredFormActionsProps {
  /** Whether the current draft passes every client-side check and is not mid-submit. */
  canSubmit: boolean
  /** True while a save is in flight — threaded through so the footer can say "Saving…". */
  busy: boolean
}

export interface WiredFormProps {
  state: WiredShareState
  interfaces: WiredInterface[]
  /** True while a request is in flight; every control goes read-only. */
  busy: boolean
  onSubmit: (config: WiredShareConfigRequest) => void
  /**
   * Start or stop sharing, now.
   *
   * The Enable switch is the one control here that is not form state: it acts
   * on its own rather than waiting for Save, because a switch reading "Sharing
   * enabled" while nothing has happened is a claim about the Pi that is not
   * true. Routed out as a callback rather than calling the store from here, so
   * the form stays drivable from fixture props alone.
   *
   * `confirmUplinkLoss` carries the operator's acknowledgement, since this
   * switch is very likely the thing that cuts this Sentry's own link.
   */
  onEnabledChange: (enabled: boolean, confirmUplinkLoss: boolean) => void
  /** Slot equivalent: builds the form's footer actions, kept current via `canSubmit`/`busy`. */
  actions: ComponentFactory<WiredFormActionsProps>
  /**
   * Slot rendered immediately above the action row, for the confirmation
   * countdown — which needs to sit with the button that caused it rather than
   * at the top of the panel. Owned by the panel; the form only reserves the
   * position.
   */
  beforeActions?: Child[]
  /** Where to mount the header toggle row. Read once — a panel does not relocate its header. */
  headerControlsHost?: HTMLElement
  /**
   * Where to mount the action row (and the countdown slot above it).
   *
   * The panel places this *after* the DHCP lease list, which sits outside the
   * form — so the row cannot simply be the form's last child. The submit button
   * is given a `form` attribute pointing back at the form's id, which is what
   * keeps Enter-to-submit and the button working from outside the element.
   */
  actionsHost?: HTMLElement
}

const INTERFACE_AUTOMATIC_OPTION: BaseSelectOption = { value: '', label: 'Choose automatically' }

/**
 * The switch reads as the state it is in, not the action it performs.
 *
 * It sits in the panel header away from any other label, so "Share port" alone
 * would leave an operator working out whether it describes what will happen or
 * what already has.
 */
function enabledToggleLabel(enabled: boolean): string {
  return enabled ? 'Sharing enabled' : 'Enable wired sharing'
}

function interfaceOptionLabel(entry: WiredInterface): string {
  if (entry.carries_default_route) {
    return `${entry.name} — carries this Sentry’s connection`
  }
  if (entry.in_use_by) {
    return `${entry.name} — in use by ${entry.in_use_by}`
  }
  // Only stated when the port is otherwise free, where it is the deciding
  // fact: an unused port with nothing in it is the one an operator is about to
  // pick and then wonder why nothing appeared.
  if (entry.carrier_up === false) {
    return `${entry.name} — nothing plugged in`
  }
  return entry.name
}

function interfaceOptions(interfaces: WiredInterface[]): BaseSelectOption[] {
  return [
    INTERFACE_AUTOMATIC_OPTION,
    ...interfaces.map((entry) => ({ value: entry.name, label: interfaceOptionLabel(entry) })),
  ]
}

/**
 * The port that will actually be used — the explicit choice, or the one
 * automatic selection would land on (the first not already carrying a link).
 *
 * Mirrors the server's own `_choose_interface` order deliberately: a form that
 * previewed a different port from the one the API would pick would put the
 * warning on the wrong row.
 */
function effectiveInterface(
  interfaces: WiredInterface[],
  selectedInterfaceName: string,
): WiredInterface | undefined {
  const explicit = interfaces.find((entry) => entry.name === selectedInterfaceName)
  if (explicit) return explicit
  return (
    interfaces.find((entry) => !entry.carries_default_route && entry.in_use_by === null) ??
    interfaces[0]
  )
}

function wouldDropUplink(interfaceDetail: WiredInterface | undefined): boolean {
  return (
    interfaceDetail !== undefined &&
    (interfaceDetail.carries_default_route || interfaceDetail.in_use_by !== null)
  )
}

/** Builds a `WiredForm`. `update` mutates every field in place. */
export function wiredForm(props: WiredFormProps): Component<WiredFormProps> {
  let currentProps = props
  let lastSeenState = props.state

  let selectedInterfaceName = props.state.interface ?? ''
  let gatewayCidr = props.state.gateway_cidr ?? ''
  let acknowledgedUplinkLoss = false

  function gatewayError(): string | null {
    return gatewayCidr === '' ? null : validateGatewayCidrClientSide(gatewayCidr)
  }
  function currentEffectiveInterface(): WiredInterface | undefined {
    return effectiveInterface(currentProps.interfaces, selectedInterfaceName)
  }
  function currentWouldDropUplink(): boolean {
    return wouldDropUplink(currentEffectiveInterface())
  }

  function computeCanSubmit(): boolean {
    return (
      !currentProps.busy &&
      gatewayError() === null &&
      (!currentWouldDropUplink() || acknowledgedUplinkLoss)
    )
  }

  const interfaceSelect = baseSelect({
    label: 'Ethernet port',
    value: selectedInterfaceName,
    onChange: (value) => {
      selectedInterfaceName = value
      render()
    },
    options: interfaceOptions(props.interfaces),
    disabled: props.busy,
  })

  const gatewayField = baseField({
    label: 'Address for cabled machines',
    value: gatewayCidr,
    onChange: (value) => {
      gatewayCidr = value
      render()
    },
    error: null,
    hint: 'The address a plugged-in machine points Sentinel at. Leave blank for this Sentry’s default. Must not overlap the hotspot’s range.',
    disabled: props.busy,
    autocomplete: 'off',
  })

  const uplinkWarning = wiredUplinkWarning({
    value: acknowledgedUplinkLoss,
    onChange: (value) => {
      acknowledgedUplinkLoss = value
      render()
    },
    interfaceName: '',
    activeConnectionName: null,
    disabled: props.busy,
  })

  /**
   * The switch is refused, not silently ignored, while sharing would cut this
   * Sentry's own link and nobody has said that is acceptable.
   *
   * The server would still refuse with `uplink_loss_unconfirmed`, but "flip
   * switch, get error" is not a safety mechanism. The warning box beside it
   * explains, and ticking its checkbox releases the switch.
   */
  function enabledToggleBlocked(): boolean {
    return currentWouldDropUplink() && !acknowledgedUplinkLoss
  }

  const enabledToggle = baseToggle({
    value: props.state.active,
    onChange: (value) => currentProps.onEnabledChange(value, acknowledgedUplinkLoss),
    label: enabledToggleLabel(props.state.active),
    accessibleName: 'Share this Sentry’s Ethernet port now',
    disabled: props.busy || enabledToggleBlocked(),
  })

  const actionsComponent = props.actions({ canSubmit: computeCanSubmit(), busy: props.busy })
  const beforeActionsSlot = el('div', { class: 'contents' }, props.beforeActions ?? [])

  // The switch lives in the panel header, not the form body — it is the control
  // an operator came to use, and on a long panel it would otherwise sit below a
  // scroll. Being outside the `<form>` element costs nothing: `submit()` reads
  // local state, never the DOM.
  const enabledToggleRow = el('div', { class: 'flex flex-wrap items-center gap-3' }, [
    enabledToggle.element,
  ])
  const headerControls = el('div', { class: 'flex flex-col items-start gap-2' }, [enabledToggleRow])
  if (props.headerControlsHost) {
    props.headerControlsHost.appendChild(headerControls)
  }

  const formId = nextElementId('wired-form')
  const formBody: Child[] = [interfaceSelect.element, gatewayField.element, uplinkWarning.element]
  const form = el(
    'form',
    {
      attrs: { novalidate: true, id: formId },
      class: 'flex flex-col gap-7',
      on: {
        submit: (event) => {
          event.preventDefault()
          submit()
        },
      },
    },
    props.actionsHost ? formBody : [...formBody, beforeActionsSlot, actionsComponent.element],
  )

  if (props.actionsHost) {
    props.actionsHost.append(beforeActionsSlot, actionsComponent.element)
    // A submit button outside its form only works when it names one. Applied to
    // every submit control in the row rather than the first, so adding a second
    // action later cannot silently become inert.
    for (const submitControl of actionsComponent.element.querySelectorAll(
      'button[type="submit"]',
    )) {
      submitControl.setAttribute('form', formId)
    }
  }

  function reseedFromState(nextState: WiredShareState): void {
    selectedInterfaceName = nextState.interface ?? ''
    gatewayCidr = nextState.gateway_cidr ?? ''
  }

  function submit(): void {
    render()
    if (!computeCanSubmit()) return

    const body: WiredShareConfigRequest = {
      // The switch acts on its own, so a save must not also flip it: `enabled`
      // states what is already true rather than proposing a change. Sending the
      // form's own idea of it would restart a share the operator had just
      // stopped, or vice versa.
      enabled: currentProps.state.active,
      confirm_uplink_loss: acknowledgedUplinkLoss,
      // Omitted rather than sent as null when left on "Choose automatically" /
      // blank, so the server applies its own default instead of being told to
      // store an empty one.
      ...(selectedInterfaceName === '' ? {} : { interface: selectedInterfaceName }),
      ...(gatewayCidr === '' ? {} : { gateway_cidr: gatewayCidr }),
    }
    currentProps.onSubmit(body)
  }

  function render(): void {
    const busy = currentProps.busy
    const effective = currentEffectiveInterface()
    const showUplinkWarning = currentWouldDropUplink()

    interfaceSelect.update({
      label: 'Ethernet port',
      value: selectedInterfaceName,
      onChange: (value) => {
        selectedInterfaceName = value
        render()
      },
      options: interfaceOptions(currentProps.interfaces),
      disabled: busy,
    })

    gatewayField.update({
      label: 'Address for cabled machines',
      value: gatewayCidr,
      onChange: (value) => {
        gatewayCidr = value
        render()
      },
      error: gatewayError(),
      hint: 'The address a plugged-in machine points Sentinel at. Leave blank for this Sentry’s default. Must not overlap the hotspot’s range.',
      disabled: busy,
      autocomplete: 'off',
    })

    setVisible(uplinkWarning.element, showUplinkWarning)
    if (showUplinkWarning && effective) {
      uplinkWarning.update({
        value: acknowledgedUplinkLoss,
        onChange: (value) => {
          acknowledgedUplinkLoss = value
          render()
        },
        interfaceName: effective.name,
        activeConnectionName: effective.in_use_by ?? null,
        disabled: busy,
      })
    }

    enabledToggle.update({
      value: currentProps.state.active,
      onChange: (value) => currentProps.onEnabledChange(value, acknowledgedUplinkLoss),
      label: enabledToggleLabel(currentProps.state.active),
      accessibleName: 'Share this Sentry’s Ethernet port now',
      disabled: busy || enabledToggleBlocked(),
    })

    actionsComponent.update({ canSubmit: computeCanSubmit(), busy })
  }

  render()

  return {
    element: form,

    update(nextProps): void {
      currentProps = nextProps
      // Re-seed only when the server hands back a genuinely different
      // configuration. Re-seeding on every store notification would overwrite
      // an address the operator is midway through typing.
      if (nextProps.state !== lastSeenState) {
        lastSeenState = nextProps.state
        reseedFromState(nextProps.state)
      }
      render()
    },

    destroy(): void {
      interfaceSelect.destroy()
      gatewayField.destroy()
      uplinkWarning.destroy()
      enabledToggle.destroy()
      actionsComponent.destroy()
      headerControls.remove()
      beforeActionsSlot.remove()
      actionsComponent.element.remove()
    },
  }
}
