<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { DeviceStatus } from '@/api/client'
import BaseToggle from '@/components/base/BaseToggle.vue'
import DataCell from '@/components/base/DataCell.vue'
import MonoValue from '@/components/base/MonoValue.vue'
import PanelCard from '@/components/base/PanelCard.vue'
import DeviceNameField from '@/components/forms/DeviceNameField.vue'
import PortAssignmentField from '@/components/forms/PortAssignmentField.vue'
import { useFleetStore } from '@/stores/fleet'

import DeviceAbsentNotice from './DeviceAbsentNotice.vue'
import DeviceStatusBadge from './DeviceStatusBadge.vue'
import NeedsIdentificationNotice from './NeedsIdentificationNotice.vue'

/**
 * One rack unit (architecture §9.5 layout): the composed, single-purpose
 * device presentation — it holds no formatting logic of its own, only
 * layout over `DeviceStatusBadge`, `DataCell`, `MonoValue` and the two
 * inline-editable form fields. This is the component `UsbTopologyTree`
 * moves focus to on Enter/Space (architecture §9.4).
 *
 * Rendered as a `PanelCard`, one per row of the centred device stack, with the
 * device's name as the card title and its make/model line beneath.
 */
const props = defineProps<{ device: DeviceStatus }>()

const emit = defineEmits<{
  'request-serial-flash': [deviceId: string]
}>()

const fleetStore = useFleetStore()

const nameDraft = ref(props.device.name)
const portDraft = ref<number | null>(props.device.output?.iq_port ?? null)

watch(
  () => props.device.name,
  (nextName) => {
    if (fleetStore.pendingPatchesByDeviceId[props.device.device_id] === undefined) {
      nameDraft.value = nextName
    }
  },
)
watch(
  () => props.device.output?.iq_port ?? null,
  (nextPort) => {
    if (fleetStore.pendingPatchesByDeviceId[props.device.device_id] === undefined) {
      portDraft.value = nextPort
    }
  },
)

// A device with no persisted record (`record_id === null`) has no row for
// the server to apply a partial PATCH to, so `{name}` alone and
// `{output_port}` alone are each individually rejected — there is no
// "unconfigured but named" or "unconfigured but ported" state on the
// server. The two fields must be validated locally and sent together in one
// combined PATCH the first time; once a record exists, independent field
// commits are correct (and cheaper) again.
const validatedNameDraft = ref<string | null>(null)
const validatedPortDraft = ref<number | null>(null)

function commitName(name: string): void {
  if (props.device.record_id === null) {
    validatedNameDraft.value = name
    attemptFirstConfigurationCommit()
    return
  }
  void fleetStore.patchDevice(props.device.device_id, { name })
}

function commitPort(port: number): void {
  if (props.device.record_id === null) {
    validatedPortDraft.value = port
    attemptFirstConfigurationCommit()
    return
  }
  void fleetStore.patchDevice(props.device.device_id, { output_port: port })
}

function attemptFirstConfigurationCommit(): void {
  if (validatedNameDraft.value === null || validatedPortDraft.value === null) {
    return
  }
  void fleetStore.patchDevice(props.device.device_id, {
    name: validatedNameDraft.value,
    output_port: validatedPortDraft.value,
  })
}

function commitEnabled(enabled: boolean): void {
  void fleetStore.patchDevice(props.device.device_id, { enabled })
}

const isEditable = computed(() => !props.device.needs_identification)
const ownReservedPorts = computed(() =>
  props.device.output ? [props.device.output.iq_port, props.device.output.control_port] : [],
)
const needsBothFieldsToConfigure = computed(
  () =>
    props.device.record_id === null &&
    (validatedNameDraft.value === null || validatedPortDraft.value === null),
)

// `usb` and `usb_last_known` are mutually exclusive (architecture §7.2): a
// present device reports the former, an absent configured one the latter.
// Falling back across both means the card renders the same identity fields
// whether the dongle is plugged in or a remembered ghost.
const identityManufacturer = computed(
  () => props.device.usb?.manufacturer ?? props.device.usb_last_known?.manufacturer ?? null,
)
const identityProduct = computed(
  () => props.device.usb?.product ?? props.device.usb_last_known?.product ?? null,
)

/** Make and model as one string, or "Unknown" — many dongles report neither. */
const identityModel = computed(
  () => [identityManufacturer.value, identityProduct.value].filter(Boolean).join(' ') || 'Unknown',
)
const identitySerial = computed(
  () => props.device.usb?.serial ?? props.device.usb_last_known?.serial ?? null,
)
</script>

<template>
  <PanelCard
    :id="`device-card-${device.device_id}`"
    as="article"
    tabindex="-1"
    class="outline-none"
  >
    <!-- Row 1 — identity and the one control that changes what the device is
         doing right now. -->
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div class="flex flex-wrap items-center gap-3">
          <h3 class="sr-only">{{ device.name || device.device_id }}</h3>
          <DeviceStatusBadge :state="device.state" :reason="device.state_reason ?? null" />
        </div>
        <BaseToggle
          v-if="device.record_id !== null"
          :model-value="device.enabled"
          :label="device.enabled ? 'Disable SDR' : 'Enable SDR'"
          :accessible-name="`${device.enabled ? 'Disable SDR' : 'Enable SDR'} — ${device.name || device.device_id}`"
          @update:model-value="commitEnabled"
        />
      </div>
    </template>

    <NeedsIdentificationNotice
      v-if="device.needs_identification"
      @request-serial-flash="emit('request-serial-flash', device.device_id)"
    />
    <DeviceAbsentNotice
      v-else-if="!device.present"
      :last-topology-path="device.usb_last_known?.topology_path ?? null"
    />

    <!-- Row 2 — the editable fields, and the relay ports they determine. Wraps
         to as many lines as the viewport needs. -->
    <div v-if="isEditable" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-start gap-x-8 gap-y-5">
        <DeviceNameField v-model="nameDraft" class="w-[220px]" @commit="commitName" />
        <PortAssignmentField
          v-model="portDraft"
          :constraints="fleetStore.constraints"
          :own-reserved-ports="ownReservedPorts"
          @commit="commitPort"
        />
      </div>
      <p v-if="needsBothFieldsToConfigure" class="m-0 text-[12px] leading-[1.6] text-signal-muted">
        Configuring a new device needs both a valid name and a valid output port — nothing is saved
        until both fields have been entered.
      </p>
    </div>

    <!-- Row 3 — what the hardware is and what it is currently tuned to.
         Read-only, and one list rather than two so all five cells share a
         single wrap context: as two adjacent lists the tuner group broke to
         its own line as a block, whatever the width. -->
    <dl class="m-0 flex flex-wrap items-start gap-x-8 gap-y-5">
      <DataCell label="Model" label-tag="dt" value-tag="dd" :value="identityModel" />
      <DataCell v-if="identitySerial" label="Serial number" label-tag="dt" value-tag="dd">
        <MonoValue :value="identitySerial" />
      </DataCell>
      <template v-if="device.tuner">
        <DataCell label="Center frequency" label-tag="dt" value-tag="dd">
          <MonoValue :value="(device.tuner.center_hz / 1_000_000).toFixed(3)" unit="MHz" />
        </DataCell>
        <DataCell label="Rate" label-tag="dt" value-tag="dd">
          <MonoValue :value="(device.tuner.sample_rate / 1_000).toFixed(0)" unit="kS/s" />
        </DataCell>
        <DataCell label="Gain" label-tag="dt" value-tag="dd">
          <!-- No unit when the tuner is in AGC: the value is a mode, not a
               measurement, and "AGC dB" reads as nonsense. -->
          <MonoValue v-if="device.tuner.gain_auto" value="AGC" />
          <MonoValue v-else :value="device.tuner.gain_db.toFixed(1)" unit="dB" />
        </DataCell>
      </template>
    </dl>
  </PanelCard>
</template>
