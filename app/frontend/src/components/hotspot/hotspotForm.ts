import { el } from '../../core/dom.js'
import type { Component, ComponentFactory } from '../../core/component.js'
import { setVisible } from '../../core/dom.js'
import type { HotspotConfigRequest, HotspotState, WirelessInterface } from '../../api/client.js'
import { baseField } from '../base/baseField.js'
import { baseSelect } from '../base/baseSelect.js'
import type { BaseSelectOption } from '../base/baseSelect.js'
import { baseToggle } from '../base/baseToggle.js'
import {
  channelOptionsForBand,
  SSID_MAX_BYTES,
  ssidByteLength,
  validateChannelClientSide,
  validateGatewayCidrClientSide,
  validatePassphraseClientSide,
  validateSsidClientSide,
} from '../../utils/hotspotValidation.js'
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
  /** Slot equivalent: builds the form's footer actions, kept current via `canSubmit`/`busy`. */
  actions: ComponentFactory<HotspotFormActionsProps>
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
  let hotspotEnabled = props.state.active
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
    return `${ssidByteLength(ssid)} of ${SSID_MAX_BYTES} bytes used. Clients must type this exactly when the network is hidden.`
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
    label: 'Hide this network',
    accessibleName: 'Hide this network from scans',
    disabled: props.busy,
  })
  const hiddenHint = el('p', { class: '-mt-3 m-0 text-[11px] leading-[1.6] text-signal-muted' }, [
    'Hidden networks do not appear in a device’s WiFi list, so clients must add them by name. This keeps casual scanners away — it is not a security measure on its own. The password is.',
  ])

  const securitySelect = baseSelect({
    label: 'Security',
    value: security,
    onChange: (value) => {
      security = value as 'wpa2' | 'wpa3'
      render()
    },
    options: SECURITY_OPTIONS,
    disabled: props.busy,
    hint: 'WPA3 is unreliable on some Raspberry Pi radios.',
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
    hint: 'Automatic avoids any radio already carrying a connection.',
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
    hint: 'Automatic is right unless you are avoiding a specific channel.',
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

  const enabledToggle = baseToggle({
    value: hotspotEnabled,
    onChange: (value) => {
      hotspotEnabled = value
      render()
    },
    label: 'Run the hotspot',
    accessibleName: 'Run the hotspot now',
    disabled: props.busy,
  })

  const actionsComponent = props.actions({ canSubmit: computeCanSubmit(), busy: props.busy })

  const form = el(
    'form',
    {
      attrs: { novalidate: true },
      class: 'flex flex-col gap-5',
      on: {
        submit: (event) => {
          event.preventDefault()
          submit()
        },
      },
    },
    [
      ssidField.element,
      passphraseField.element,
      hiddenToggle.element,
      hiddenHint,
      selectGrid,
      gatewayField.element,
      uplinkWarning.element,
      enabledToggle.element,
      actionsComponent.element,
    ],
  )

  function reseedFromState(nextState: HotspotState): void {
    ssid = nextState.ssid ?? ''
    security = nextState.security ?? 'wpa2'
    hidden = nextState.hidden ?? true
    hotspotEnabled = nextState.active
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
      enabled: hotspotEnabled,
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
      label: 'Hide this network',
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
      hint: 'WPA3 is unreliable on some Raspberry Pi radios.',
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
      hint: 'Automatic avoids any radio already carrying a connection.',
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
      hint: 'Automatic is right unless you are avoiding a specific channel.',
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
      value: hotspotEnabled,
      onChange: (value) => {
        hotspotEnabled = value
        render()
      },
      label: 'Run the hotspot',
      accessibleName: 'Run the hotspot now',
      disabled: busy,
    })

    actionsComponent.update({ canSubmit: computeCanSubmit(), busy })
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
