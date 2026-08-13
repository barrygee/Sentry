import { el } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component, ComponentFactory } from '../../core/component.js'
import { setVisible } from '../../core/dom.js'
import type { HotspotConfigRequest, HotspotState, WirelessInterface } from '../../api/client.js'
import { baseField } from '../base/baseField.js'
import { baseSelect } from '../base/baseSelect.js'
import type { BaseSelectOption } from '../base/baseSelect.js'
import { baseToggle } from '../base/baseToggle.js'
import { nextElementId } from '../base/idGenerator.js'
import {
  channelOptionsForBand,
  SSID_MAX_BYTES,
  ssidByteLength,
  validateChannelClientSide,
  validateGatewayCidrClientSide,
  validatePassphraseClientSide,
  validateSsidClientSide,
} from '../../utils/hotspotValidation.js'
import { syncChildren } from '../base/childrenSync.js'
import { hotspotPassphraseField } from './hotspotPassphraseField.js'
import { hotspotUplinkWarning } from './hotspotUplinkWarning.js'

/**
 * The hotspot settings form.
 *
 * Calls `onSubmit` with a complete `HotspotConfigRequest` rather than
 * mutating any store directly, so the whole form is drivable from fixture
 * props alone.
 *
 * Two details carry most of the design weight:
 *
 * 1. **The passphrase key is omitted entirely** from the submitted body when
 *    the operator has not chosen to change it. That omission is the wire
 *    signal for "keep the stored password".
 * 2. **The uplink warning is driven by the selected interface**, not by
 *    whether the server last complained. Choosing the radio that carries
 *    this Sentry's own connection surfaces the warning immediately, so the
 *    acknowledgement is a decision rather than a reaction to a rejected
 *    save.
 */
export interface HotspotFormActionsProps {
  /** Whether the current draft passes every client-side check and is not mid-submit. */
  canSubmit: boolean
  /** True while a save is in flight — threaded through so the actions footer can say "Saving…". */
  busy: boolean
}

export interface HotspotFormProps {
  state: HotspotState
  interfaces: WirelessInterface[]
  /** True while a request is in flight; every control goes read-only. */
  busy: boolean
  onSubmit: (config: HotspotConfigRequest) => void
  /**
   * Start or stop the hotspot, now.
   *
   * The Enable switch is the one control here that is not form state: it acts
   * on its own rather than waiting for Save, because a switch that reports
   * "Hotspot enabled" while nothing has happened is a claim about the Pi that
   * is not true. Routed out as a callback rather than calling the store from
   * here, so the form stays drivable from fixture props alone.
   *
   * `confirmUplinkLoss` carries the operator's acknowledgement, since the
   * switch can now be the thing that cuts this Sentry's own link.
   */
  onEnabledChange: (enabled: boolean, confirmUplinkLoss: boolean) => void
  /** Slot equivalent: builds the form's footer actions, kept current via `canSubmit`/`busy`. */
  actions: ComponentFactory<HotspotFormActionsProps>
  /**
   * Slot rendered immediately above the action row.
   *
   * For the confirmation countdown, which needs to sit with the button that
   * caused it rather than at the top of the panel. Owned by the panel — the
   * form neither builds nor updates what goes in here, it only reserves the
   * position.
   */
  beforeActions?: Child[]
  /**
   * Where to mount the header toggle row.
   *
   * The panel owns the header, so it supplies the element and the form fills
   * it once at construction. Read once — a panel does not relocate its own
   * header mid-life.
   */
  headerControlsHost?: HTMLElement
  /**
   * Where to mount the action row (and the countdown slot above it).
   *
   * The panel places this *after* the DHCP lease list, which sits outside the
   * form — so the row cannot simply be the form's last child. Mounted here
   * instead, with the submit button given a `form` attribute pointing back at
   * the form's id, which is what keeps Enter-to-submit and the button working
   * from outside the element.
   */
  actionsHost?: HTMLElement
}

const INTERFACE_AUTOMATIC_OPTION: BaseSelectOption = { value: '', label: 'Choose automatically' }
const SECURITY_OPTIONS: BaseSelectOption[] = [
  { value: 'wpa2', label: 'WPA2-Personal' },
  { value: 'wpa3', label: 'WPA3-Personal (experimental)' },
]
const BAND_OPTIONS: BaseSelectOption[] = [
  { value: 'bg', label: '2.4 GHz (longer range)' },
  { value: 'a', label: '5 GHz (faster, shorter range)' },
]

/**
 * The toggles read as the state they are in, not the action they perform.
 *
 * They sit in the panel header away from any other label, so "Hide network"
 * alone leaves an operator working out whether it describes what will happen
 * or what already has. Naming the resulting condition when on removes that.
 */
function hiddenToggleLabel(hidden: boolean): string {
  return hidden ? 'Network is hidden' : 'Hide network'
}

function enabledToggleLabel(enabled: boolean): string {
  return enabled ? 'Hotspot enabled' : 'Enable hotspot'
}

function interfaceOptionLabel(entry: WirelessInterface): string {
  return entry.carries_default_route
    ? `${entry.name} — in use by ${entry.station_ssid ?? 'this Sentry’s connection'}`
    : entry.name
}

function interfaceOptions(interfaces: WirelessInterface[]): BaseSelectOption[] {
  return [
    INTERFACE_AUTOMATIC_OPTION,
    ...interfaces.map((entry) => ({ value: entry.name, label: interfaceOptionLabel(entry) })),
  ]
}

/**
 * The interface that will actually be used — the explicit choice, or the one
 * automatic selection would land on (the first not already carrying a link).
 */
function effectiveInterface(
  interfaces: WirelessInterface[],
  selectedInterfaceName: string,
): WirelessInterface | undefined {
  const explicit = interfaces.find((entry) => entry.name === selectedInterfaceName)
  if (explicit) return explicit
  return (
    interfaces.find((entry) => !entry.carries_default_route && entry.in_use_by === null) ??
    interfaces[0]
  )
}

function wouldDropUplink(interfaceDetail: WirelessInterface | undefined): boolean {
  return (
    interfaceDetail !== undefined &&
    (interfaceDetail.carries_default_route || interfaceDetail.in_use_by !== null)
  )
}

/**
 * Builds a `HotspotForm`. `update` mutates every field in place — the SSID,
 * passphrase and gateway address are typed into, and re-seeding the form on
 * every store notification (rather than only when the server hands back a
 * genuinely different configuration) would fight the operator's own typing.
 */
export function hotspotForm(props: HotspotFormProps): Component<HotspotFormProps> {
  let currentProps = props
  let lastSeenState = props.state

  let ssid = props.state.ssid ?? ''
  let passphrase = ''
  let passphraseChanging = !props.state.passphrase_set
  let security: 'wpa2' | 'wpa3' = props.state.security ?? 'wpa2'
  let hidden = props.state.hidden ?? true
  let selectedInterfaceName = props.state.interface ?? ''
  let band: 'bg' | 'a' = props.state.band ?? 'bg'
  let channel = String(props.state.channel ?? 0)
  let gatewayCidr = props.state.gateway_cidr ?? ''
  let acknowledgedUplinkLoss = false
  let ssidTouched = false

  function ssidError(): string | null {
    return ssidTouched ? validateSsidClientSide(ssid) : null
  }
  function ssidHint(): string {
    return `${ssidByteLength(ssid)} of ${SSID_MAX_BYTES} characters used.`
  }
  function channelError(): string | null {
    return validateChannelClientSide(Number(channel), band)
  }
  function gatewayError(): string | null {
    return gatewayCidr === '' ? null : validateGatewayCidrClientSide(gatewayCidr)
  }
  function passphraseMissing(): boolean {
    return passphraseChanging && passphrase === '' && !currentProps.state.passphrase_set
  }
  function passphraseError(): string | null {
    if (!passphraseChanging || passphrase === '') return null
    return validatePassphraseClientSide(passphrase)
  }
  function currentEffectiveInterface(): WirelessInterface | undefined {
    return effectiveInterface(currentProps.interfaces, selectedInterfaceName)
  }
  function currentWouldDropUplink(): boolean {
    return wouldDropUplink(currentEffectiveInterface())
  }
  /** Whether either header switch is showing something the Pi is not doing yet. */
  function hiddenDiffersFromServer(): boolean {
    return hidden !== (currentProps.state.hidden ?? true)
  }

  function computeCanSubmit(): boolean {
    return (
      !currentProps.busy &&
      validateSsidClientSide(ssid) === null &&
      channelError() === null &&
      gatewayError() === null &&
      passphraseError() === null &&
      !passphraseMissing() &&
      (!currentWouldDropUplink() || acknowledgedUplinkLoss)
    )
  }

  const ssidField = baseField({
    label: 'Network name (SSID)',
    value: ssid,
    onChange: (value) => {
      ssid = value
      render()
    },
    error: null,
    hint: ssidHint(),
    disabled: props.busy,
    autocomplete: 'off',
    onBlur: () => {
      ssidTouched = true
      render()
    },
  })

  const passphraseField = hotspotPassphraseField({
    value: passphrase,
    onChange: (value) => {
      passphrase = value
      render()
    },
    passphraseSet: props.state.passphrase_set,
    disabled: props.busy,
    onChangingUpdate: (changing) => {
      passphraseChanging = changing
      render()
    },
  })

  const hiddenToggle = baseToggle({
    value: hidden,
    onChange: (value) => {
      hidden = value
      render()
    },
    label: hiddenToggleLabel(hidden),
    accessibleName: 'Hide this network from scans',
    disabled: props.busy,
  })

  const securitySelect = baseSelect({
    label: 'Security',
    value: security,
    onChange: (value) => {
      security = value as 'wpa2' | 'wpa3'
      render()
    },
    options: SECURITY_OPTIONS,
    disabled: props.busy,
  })
  const interfaceSelect = baseSelect({
    label: 'Wireless interface',
    value: selectedInterfaceName,
    onChange: (value) => {
      selectedInterfaceName = value
      render()
    },
    options: interfaceOptions(props.interfaces),
    disabled: props.busy,
  })
  const bandSelect = baseSelect({
    label: 'Band',
    value: band,
    onChange: (value) => {
      band = value as 'bg' | 'a'
      // A channel legal on 2.4 GHz is meaningless on 5 GHz, so switching band
      // resets it to Automatic rather than leaving an invalid value selected.
      channel = '0'
      render()
    },
    options: BAND_OPTIONS,
    disabled: props.busy,
  })
  const channelSelect = baseSelect({
    label: 'Channel',
    value: channel,
    onChange: (value) => {
      channel = value
      render()
    },
    options: channelOptionsForBand(band),
    error: channelError(),
    disabled: props.busy,
  })
  const selectGrid = el('div', { class: 'grid gap-5 sm:grid-cols-2' }, [
    securitySelect.element,
    interfaceSelect.element,
    bandSelect.element,
    channelSelect.element,
  ])

  const gatewayField = baseField({
    label: 'Address for clients',
    value: gatewayCidr,
    onChange: (value) => {
      gatewayCidr = value
      render()
    },
    error: null,
    hint: 'The address a joined client points Sentinel at. Leave blank for this Sentry’s default.',
    disabled: props.busy,
    autocomplete: 'off',
  })

  const uplinkWarning = hotspotUplinkWarning({
    value: acknowledgedUplinkLoss,
    onChange: (value) => {
      acknowledgedUplinkLoss = value
      render()
    },
    interfaceName: '',
    stationSsid: null,
    disabled: props.busy,
  })

  /**
   * The switch is refused, not silently ignored, while starting the hotspot
   * would cut this Sentry's own link and nobody has said that is acceptable.
   *
   * That acknowledgement used to gate Save alone. Now that the switch acts on
   * its own it would otherwise walk straight past the one check standing
   * between an operator and a Pi they can no longer reach — the server would
   * still refuse with `uplink_loss_unconfirmed`, but "flip switch, get error"
   * is not a safety mechanism. The warning box beside it explains, and ticking
   * its checkbox releases the switch.
   */
  function enabledToggleBlocked(): boolean {
    return currentWouldDropUplink() && !acknowledgedUplinkLoss
  }

  const enabledToggle = baseToggle({
    value: props.state.active,
    onChange: (value) => currentProps.onEnabledChange(value, acknowledgedUplinkLoss),
    label: enabledToggleLabel(props.state.active),
    accessibleName: 'Run the hotspot now',
    disabled: props.busy || enabledToggleBlocked(),
  })

  const actionsComponent = props.actions({ canSubmit: computeCanSubmit(), busy: props.busy })
  const beforeActionsSlot = el('div', { class: 'contents' }, props.beforeActions ?? [])

  // Both toggles live in the panel header, not the form body. They are the two
  // controls an operator reaches for most and the only ones worth reading at a
  // glance; buried between fields they were easy to miss, and "Run the hotspot"
  // sat below a scroll on a long panel. Being outside the `<form>` element
  // costs nothing — `submit()` reads local state, never the DOM.
  // Stacked and left-aligned, below the header text. Enable comes first: it is
  // the one an operator came to use, and hiding a network is a property of a
  // hotspot that is already running.
  // Beside the switch it qualifies, not below the pair. Under both toggles it
  // was a caption on the group, and the label directly above it — "Hotspot
  // enabled" — reads as a statement of fact in the same weight as every other
  // readout on the panel. A qualifier two rows down does not win that
  // argument; one on the same line does.
  //
  // Neither switch acts on its own: both are form state, applied by "Save
  // hotspot settings" like every other field. So each gets its own, shown only
  // while that switch disagrees with the server.
  //
  // Not live regions. The panel already has one for save progress, and further
  // `role="status"` elements compete with it for the same announcement queue.
  const PENDING_NOTICE_CLASS = 'm-0 text-[11px] leading-[1.6] text-signal-muted'
  const PENDING_NOTICE_TEXT = 'Not applied until you save'

  const hiddenPendingNotice = el('p', { class: PENDING_NOTICE_CLASS }, [PENDING_NOTICE_TEXT])

  const enabledToggleRow = el('div', { class: 'flex flex-wrap items-center gap-3' }, [
    enabledToggle.element,
  ])
  const hiddenToggleRow = el('div', { class: 'flex flex-wrap items-center gap-3' }, [
    hiddenToggle.element,
    hiddenPendingNotice,
  ])

  const headerControls = el('div', { class: 'flex flex-col items-start gap-2' }, [
    enabledToggleRow,
    hiddenToggleRow,
  ])
  if (props.headerControlsHost) {
    props.headerControlsHost.appendChild(headerControls)
  }

  const formId = nextElementId('hotspot-form')
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
    props.actionsHost
      ? [
          ssidField.element,
          passphraseField.element,
          selectGrid,
          gatewayField.element,
          uplinkWarning.element,
        ]
      : [
          ssidField.element,
          passphraseField.element,
          selectGrid,
          gatewayField.element,
          uplinkWarning.element,
          beforeActionsSlot,
          actionsComponent.element,
        ],
  )

  if (props.actionsHost) {
    props.actionsHost.append(beforeActionsSlot, actionsComponent.element)
    // A submit button outside its form only works when it names one. Applied
    // to every submit control in the row rather than the first, so adding a
    // second action later cannot silently become inert.
    for (const submitControl of actionsComponent.element.querySelectorAll(
      'button[type="submit"]',
    )) {
      submitControl.setAttribute('form', formId)
    }
  }

  function reseedFromState(nextState: HotspotState): void {
    ssid = nextState.ssid ?? ''
    security = nextState.security ?? 'wpa2'
    hidden = nextState.hidden ?? true
    selectedInterfaceName = nextState.interface ?? ''
    band = nextState.band ?? 'bg'
    channel = String(nextState.channel ?? 0)
    gatewayCidr = nextState.gateway_cidr ?? ''
  }

  function submit(): void {
    ssidTouched = true
    render()
    if (!computeCanSubmit()) return

    const body: HotspotConfigRequest = {
      ssid,
      security,
      hidden,
      // The server's own value, not a draft. `enabled` defaults to false in
      // the request schema, so omitting it would stop a running hotspot on an
      // unrelated save; echoing what is already true makes Save neutral about
      // running state, which the switch now owns.
      enabled: currentProps.state.active,
      interface: selectedInterfaceName === '' ? null : selectedInterfaceName,
      band,
      channel: Number(channel),
      // Empty means "use whatever this deployment configured", which is what
      // the server does with null — so an untouched field never pins an
      // address.
      gateway_cidr: gatewayCidr === '' ? null : gatewayCidr,
      confirm_uplink_loss: acknowledgedUplinkLoss,
    }
    // Present ONLY when the operator actually set one. Its absence is what
    // tells the server to keep the stored password.
    if (passphraseChanging && passphrase !== '') {
      body.passphrase = passphrase
    }
    currentProps.onSubmit(body)
  }

  function render(): void {
    const busy = currentProps.busy
    const interfaces = currentProps.interfaces

    setVisible(hiddenPendingNotice, hiddenDiffersFromServer())

    ssidField.update({
      label: 'Network name (SSID)',
      value: ssid,
      onChange: (value) => {
        ssid = value
        render()
      },
      error: ssidError(),
      hint: ssidError() ? null : ssidHint(),
      disabled: busy,
      autocomplete: 'off',
      onBlur: () => {
        ssidTouched = true
        render()
      },
    })

    passphraseField.update({
      value: passphrase,
      onChange: (value) => {
        passphrase = value
        render()
      },
      passphraseSet: currentProps.state.passphrase_set,
      disabled: busy,
      onChangingUpdate: (changing) => {
        passphraseChanging = changing
        render()
      },
    })

    hiddenToggle.update({
      value: hidden,
      onChange: (value) => {
        hidden = value
        render()
      },
      label: hiddenToggleLabel(hidden),
      accessibleName: 'Hide this network from scans',
      disabled: busy,
    })

    securitySelect.update({
      label: 'Security',
      value: security,
      onChange: (value) => {
        security = value as 'wpa2' | 'wpa3'
        render()
      },
      options: SECURITY_OPTIONS,
      disabled: busy,
    })
    interfaceSelect.update({
      label: 'Wireless interface',
      value: selectedInterfaceName,
      onChange: (value) => {
        selectedInterfaceName = value
        render()
      },
      options: interfaceOptions(interfaces),
      disabled: busy,
    })
    bandSelect.update({
      label: 'Band',
      value: band,
      onChange: (value) => {
        band = value as 'bg' | 'a'
        channel = '0'
        render()
      },
      options: BAND_OPTIONS,
      disabled: busy,
    })
    channelSelect.update({
      label: 'Channel',
      value: channel,
      onChange: (value) => {
        channel = value
        render()
      },
      options: channelOptionsForBand(band),
      error: channelError(),
      disabled: busy,
    })

    gatewayField.update({
      label: 'Address for clients',
      value: gatewayCidr,
      onChange: (value) => {
        gatewayCidr = value
        render()
      },
      error: gatewayError(),
      hint: gatewayError()
        ? null
        : 'The address a joined client points Sentinel at. Leave blank for this Sentry’s default.',
      disabled: busy,
      autocomplete: 'off',
    })

    const dropsUplink = currentWouldDropUplink()
    const effective = currentEffectiveInterface()
    setVisible(uplinkWarning.element, dropsUplink && effective !== undefined)
    if (effective) {
      uplinkWarning.update({
        value: acknowledgedUplinkLoss,
        onChange: (value) => {
          acknowledgedUplinkLoss = value
          render()
        },
        interfaceName: effective.name,
        stationSsid: effective.station_ssid ?? null,
        disabled: busy,
      })
    }

    enabledToggle.update({
      // Reflects the server, never a draft: the switch now reports what the
      // hotspot is doing rather than what will happen on Save.
      value: currentProps.state.active,
      onChange: (value) => currentProps.onEnabledChange(value, acknowledgedUplinkLoss),
      label: enabledToggleLabel(currentProps.state.active),
      accessibleName: 'Run the hotspot now',
      disabled: busy || enabledToggleBlocked(),
    })

    actionsComponent.update({ canSubmit: computeCanSubmit(), busy })
    syncChildren(beforeActionsSlot, currentProps.beforeActions ?? [])
  }

  render()

  return {
    element: form,

    update(nextProps): void {
      const stateChanged = nextProps.state !== lastSeenState
      currentProps = nextProps
      if (stateChanged) {
        lastSeenState = nextProps.state
        // Never mid-flight, which would yank the form out from under someone
        // typing.
        if (!nextProps.busy) {
          reseedFromState(nextProps.state)
        }
      }
      render()
    },

    destroy(): void {
      // The header row lives in the panel's element, not this component's, so
      // it does not go away with the form's own subtree — it has to be removed
      // by hand or a rebuilt form leaves a dead set of toggles behind it.
      headerControls.remove()
      // Same reasoning: these live in the panel's element, not this one's.
      beforeActionsSlot.remove()
      actionsComponent.element.remove()
      ssidField.destroy()
      passphraseField.destroy()
      hiddenToggle.destroy()
      securitySelect.destroy()
      interfaceSelect.destroy()
      bandSelect.destroy()
      channelSelect.destroy()
      gatewayField.destroy()
      uplinkWarning.destroy()
      enabledToggle.destroy()
      actionsComponent.destroy()
    },
  }
}
