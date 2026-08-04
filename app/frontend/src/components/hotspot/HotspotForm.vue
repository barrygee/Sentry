<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { HotspotConfigRequest, HotspotState, WirelessInterface } from '@/api/client'
import BaseField from '@/components/base/BaseField.vue'
import BaseSelect from '@/components/base/BaseSelect.vue'
import BaseToggle from '@/components/base/BaseToggle.vue'
import HotspotPassphraseField from '@/components/hotspot/HotspotPassphraseField.vue'
import HotspotUplinkWarning from '@/components/hotspot/HotspotUplinkWarning.vue'
import {
  channelOptionsForBand,
  SSID_MAX_BYTES,
  ssidByteLength,
  validateChannelClientSide,
  validateGatewayCidrClientSide,
  validatePassphraseClientSide,
  validateSsidClientSide,
} from '@/utils/hotspotValidation'

/**
 * The hotspot settings form.
 *
 * Emits a complete `HotspotConfigRequest` on submit rather than mutating the
 * store directly, so the whole form is drivable from fixture props alone.
 *
 * Two details carry most of the design weight:
 *
 * 1. **The passphrase key is omitted entirely** from the emitted body when the
 *    operator has not chosen to change it. `undefined` would serialise away
 *    anyway, but building it explicitly keeps the intent visible — that
 *    omission is the wire signal for "keep the stored password".
 * 2. **The uplink warning is driven by the selected interface**, not by whether
 *    the server last complained. Choosing the radio that carries this Sentry's
 *    own connection surfaces the warning immediately, so the acknowledgement is
 *    a decision rather than a reaction to a rejected save.
 */
const props = defineProps<{
  state: HotspotState
  interfaces: WirelessInterface[]
  /** True while a request is in flight; every control goes read-only. */
  busy: boolean
}>()

const emit = defineEmits<{ submit: [HotspotConfigRequest] }>()

const ssid = ref(props.state.ssid ?? '')
const passphrase = ref('')
const passphraseChanging = ref(!props.state.passphrase_set)
const security = ref<'wpa2' | 'wpa3'>(props.state.security ?? 'wpa2')
const hidden = ref(props.state.hidden ?? true)
const enabled = ref(props.state.active)
const selectedInterface = ref(props.state.interface ?? '')
const band = ref<'bg' | 'a'>(props.state.band ?? 'bg')
const channel = ref(String(props.state.channel ?? 0))
const gatewayCidr = ref(props.state.gateway_cidr ?? '')
const acknowledgedUplinkLoss = ref(false)
const ssidTouched = ref(false)

// Re-seed the draft whenever the server hands back a different configuration
// (a save, a rollback, a reopen) — but never mid-flight, which would yank the
// form out from under someone typing.
watch(
  () => props.state,
  (nextState) => {
    if (props.busy) return
    ssid.value = nextState.ssid ?? ''
    security.value = nextState.security ?? 'wpa2'
    hidden.value = nextState.hidden ?? true
    enabled.value = nextState.active
    selectedInterface.value = nextState.interface ?? ''
    band.value = nextState.band ?? 'bg'
    channel.value = String(nextState.channel ?? 0)
    gatewayCidr.value = nextState.gateway_cidr ?? ''
  },
)

const interfaceOptions = computed(() => [
  { value: '', label: 'Choose automatically' },
  ...props.interfaces.map((entry) => ({
    value: entry.name,
    label: entry.carries_default_route
      ? `${entry.name} — in use by ${entry.station_ssid ?? 'this Sentry’s connection'}`
      : entry.name,
  })),
])

const channelOptions = computed(() => channelOptionsForBand(band.value))

// A channel legal on 2.4 GHz is meaningless on 5 GHz, so switching band resets
// it to Automatic rather than leaving an invalid value selected.
watch(band, () => {
  channel.value = '0'
})

const selectedInterfaceDetail = computed(() =>
  props.interfaces.find((entry) => entry.name === selectedInterface.value),
)

/**
 * The interface that will actually be used — the explicit choice, or the one
 * automatic selection would land on (the first not already carrying a link).
 */
const effectiveInterface = computed(() => {
  if (selectedInterfaceDetail.value) return selectedInterfaceDetail.value
  return (
    props.interfaces.find((entry) => !entry.carries_default_route && entry.in_use_by === null) ??
    props.interfaces[0]
  )
})

const wouldDropUplink = computed(
  () =>
    effectiveInterface.value !== undefined &&
    (effectiveInterface.value.carries_default_route || effectiveInterface.value.in_use_by !== null),
)

const gatewayError = computed(() =>
  gatewayCidr.value === '' ? null : validateGatewayCidrClientSide(gatewayCidr.value),
)

const ssidError = computed(() => (ssidTouched.value ? validateSsidClientSide(ssid.value) : null))
const channelError = computed(() => validateChannelClientSide(Number(channel.value), band.value))

const ssidHint = computed(
  () =>
    `${ssidByteLength(ssid.value)} of ${SSID_MAX_BYTES} bytes used. Clients must type this exactly when the network is hidden.`,
)

const passphraseMissing = computed(
  () => passphraseChanging.value && passphrase.value === '' && !props.state.passphrase_set,
)

/**
 * A typed-but-invalid passphrase blocks submit; an empty one does not, because
 * on a configured hotspot "empty" means "keep the stored password".
 */
const passphraseError = computed(() => {
  if (!passphraseChanging.value || passphrase.value === '') return null
  return validatePassphraseClientSide(passphrase.value)
})

const canSubmit = computed(
  () =>
    !props.busy &&
    validateSsidClientSide(ssid.value) === null &&
    channelError.value === null &&
    gatewayError.value === null &&
    passphraseError.value === null &&
    !passphraseMissing.value &&
    (!wouldDropUplink.value || acknowledgedUplinkLoss.value),
)

function submit(): void {
  ssidTouched.value = true
  if (!canSubmit.value) return

  const body: HotspotConfigRequest = {
    ssid: ssid.value,
    security: security.value,
    hidden: hidden.value,
    enabled: enabled.value,
    interface: selectedInterface.value === '' ? null : selectedInterface.value,
    band: band.value,
    channel: Number(channel.value),
    // Empty means "use whatever this deployment configured", which is what the
    // server does with null — so an untouched field never pins an address.
    gateway_cidr: gatewayCidr.value === '' ? null : gatewayCidr.value,
    confirm_uplink_loss: acknowledgedUplinkLoss.value,
  }
  // Present ONLY when the operator actually set one. Its absence is what tells
  // the server to keep the stored password.
  if (passphraseChanging.value && passphrase.value !== '') {
    body.passphrase = passphrase.value
  }
  emit('submit', body)
}
</script>

<template>
  <form class="flex flex-col gap-5" novalidate @submit.prevent="submit">
    <BaseField
      v-model="ssid"
      label="Network name (SSID)"
      :error="ssidError"
      :hint="ssidError ? null : ssidHint"
      :disabled="props.busy"
      autocomplete="off"
      @blur="ssidTouched = true"
    />

    <HotspotPassphraseField
      v-model="passphrase"
      :passphrase-set="state.passphrase_set"
      :disabled="props.busy"
      @update:changing="passphraseChanging = $event"
    />

    <BaseToggle
      v-model="hidden"
      label="Hide this network"
      accessible-name="Hide this network from scans"
      :disabled="props.busy"
    />
    <p class="-mt-3 m-0 text-[11px] leading-[1.6] text-signal-muted">
      Hidden networks do not appear in a device’s WiFi list, so clients must add them by name. This
      keeps casual scanners away — it is not a security measure on its own. The password is.
    </p>

    <div class="grid gap-5 sm:grid-cols-2">
      <BaseSelect
        v-model="security"
        label="Security"
        :options="[
          { value: 'wpa2', label: 'WPA2-Personal' },
          { value: 'wpa3', label: 'WPA3-Personal (experimental)' },
        ]"
        :disabled="props.busy"
        hint="WPA3 is unreliable on some Raspberry Pi radios."
      />
      <BaseSelect
        v-model="selectedInterface"
        label="Wireless interface"
        :options="interfaceOptions"
        :disabled="props.busy"
        hint="Automatic avoids any radio already carrying a connection."
      />
      <BaseSelect
        v-model="band"
        label="Band"
        :options="[
          { value: 'bg', label: '2.4 GHz (longer range)' },
          { value: 'a', label: '5 GHz (faster, shorter range)' },
        ]"
        :disabled="props.busy"
      />
      <BaseSelect
        v-model="channel"
        label="Channel"
        :options="channelOptions"
        :error="channelError"
        :disabled="props.busy"
        hint="Automatic is right unless you are avoiding a specific channel."
      />
    </div>

    <BaseField
      v-model="gatewayCidr"
      label="Address for clients"
      :error="gatewayError"
      :hint="
        gatewayError
          ? null
          : 'The address a joined client points Sentinel at. Leave blank for this Sentry\u2019s default.'
      "
      :disabled="props.busy"
      autocomplete="off"
    />

    <HotspotUplinkWarning
      v-if="wouldDropUplink && effectiveInterface"
      v-model="acknowledgedUplinkLoss"
      :interface-name="effectiveInterface.name"
      :station-ssid="effectiveInterface.station_ssid ?? null"
      :disabled="props.busy"
    />

    <BaseToggle
      v-model="enabled"
      label="Run the hotspot"
      accessible-name="Run the hotspot now"
      :disabled="props.busy"
    />

    <slot name="actions" :can-submit="canSubmit" :submit="submit" />
  </form>
</template>
