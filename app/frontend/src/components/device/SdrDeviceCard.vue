<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { DeviceStatus } from '@/api/client'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseToggle from '@/components/base/BaseToggle.vue'
import DataCell from '@/components/base/DataCell.vue'
import MonoValue from '@/components/base/MonoValue.vue'
import PanelCard from '@/components/base/PanelCard.vue'
import DeviceNameField from '@/components/forms/DeviceNameField.vue'
import PortAssignmentField from '@/components/forms/PortAssignmentField.vue'
import { useFleetStore } from '@/stores/fleet'

import DeviceAbsentNotice from './DeviceAbsentNotice.vue'
import DeviceIdentitySummary from './DeviceIdentitySummary.vue'
import DeviceStatusBadge from './DeviceStatusBadge.vue'
import JackPair from './JackPair.vue'
import NeedsIdentificationNotice from './NeedsIdentificationNotice.vue'

/**
 * One rack unit (architecture §9.5 layout): the composed, single-purpose
 * device presentation — it holds no formatting logic of its own, only
 * layout over `DeviceStatusBadge`, `JackPair`, `MonoValue` and the two
 * inline-editable form fields. This is the component `UsbTopologyTree`
 * moves focus to on Enter/Space (architecture §9.4).
 *
 * Rendered as a `PanelCard`, one per row of the centred device stack, with the
 * device's name as the card title and its make/model line beneath.
 */
const props = defineProps<{ device: DeviceStatus }>()

const emit = defineEmits<{
  'request-serial-flash': [deviceId: string]
  /** Only ever raised for an absent, configured device (`FleetView` renders the control accordingly). */
  'request-forget-device': [deviceId: string]
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
// Falling back across both lets `DeviceIdentitySummary` stay ignorant of
// which state the card is in.
const identityManufacturer = computed(
  () => props.device.usb?.manufacturer ?? props.device.usb_last_known?.manufacturer ?? null,
)
const identityProduct = computed(
  () => props.device.usb?.product ?? props.device.usb_last_known?.product ?? null,
)
const identitySerial = computed(
  () => props.device.usb?.serial ?? props.device.usb_last_known?.serial ?? null,
)

/** The forget/delete control only ever makes sense for a configured device that is currently absent — the server itself refuses to delete a live one. */
const isForgettable = computed(() => !props.device.present && props.device.record_id !== null)
</script>

<template>
  <PanelCard
    :id="`device-card-${device.device_id}`"
    as="article"
    tabindex="-1"
    class="outline-none"
  >
    <template #header>
      <div class="flex flex-col gap-1.5">
        <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <h3
              class="m-0 font-condensed text-[14px] font-normal uppercase tracking-readout text-ink-primary"
            >
              {{ device.name || device.device_id }}
            </h3>
            <DeviceStatusBadge :state="device.state" :reason="device.state_reason ?? null" />
          </div>
          <div class="flex items-center gap-3">
            <BaseButton
              v-if="isForgettable"
              variant="danger"
              @click="emit('request-forget-device', device.device_id)"
            >
              Forget device
            </BaseButton>
            <BaseToggle
              v-if="device.record_id !== null"
              :model-value="device.enabled"
              :label="`Enabled — ${device.name || device.device_id}`"
              @update:model-value="commitEnabled"
            />
          </div>
        </div>
        <DeviceIdentitySummary
          :manufacturer="identityManufacturer"
          :product="identityProduct"
          :serial="identitySerial"
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

    <div class="flex flex-wrap items-start gap-8">
      <JackPair
        :iq-port="device.output?.iq_port ?? null"
        :control-port="device.output?.control_port ?? null"
      />
      <!-- Sentinel's telemetry cells (`BaseDataCell`): caption above value,
           no fill behind either. -->
      <dl v-if="device.tuner" class="m-0 flex flex-wrap items-start gap-8">
        <DataCell label="Center" label-tag="dt" value-tag="dd">
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
      </dl>
    </div>

    <div v-if="isEditable" class="flex flex-col gap-2">
      <!-- Stacked, not side by side: one field per row reads as a form. Each
           is capped near the length of what it holds — a 64-char name and a
           4-digit port — rather than stretched to the card's full width, which
           left an input several times wider than any value it can contain. -->
      <div class="flex flex-col items-start gap-3">
        <DeviceNameField v-model="nameDraft" class="w-full max-w-[340px]" @commit="commitName" />
        <PortAssignmentField
          v-model="portDraft"
          :constraints="fleetStore.constraints"
          :own-reserved-ports="ownReservedPorts"
          :committed-iq-port="device.output?.iq_port ?? null"
          class="w-full max-w-[220px]"
          @commit="commitPort"
        />
      </div>
      <p v-if="needsBothFieldsToConfigure" class="m-0 text-[12px] leading-[1.6] text-signal-muted">
        Configuring a new device needs both a valid name and a valid output port — nothing is saved
        until both fields have been entered.
      </p>
    </div>
  </PanelCard>
</template>
