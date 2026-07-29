<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { DeviceStatus } from '@/api/client'
import BaseToggle from '@/components/base/BaseToggle.vue'
import MonoValue from '@/components/base/MonoValue.vue'
import DeviceNameField from '@/components/forms/DeviceNameField.vue'
import PortAssignmentField from '@/components/forms/PortAssignmentField.vue'
import { useFleetStore } from '@/stores/fleet'
import { DEVICE_STATE_META, type DeviceState } from '@/utils/deviceState'

import DeviceAbsentNotice from './DeviceAbsentNotice.vue'
import DeviceStatusBadge from './DeviceStatusBadge.vue'
import JackPair from './JackPair.vue'
import NeedsIdentificationNotice from './NeedsIdentificationNotice.vue'

/**
 * One rack unit (architecture §9.5 layout): the composed, single-purpose
 * device presentation — it holds no formatting logic of its own, only
 * layout over `DeviceStatusBadge`, `JackPair`, `MonoValue` and the two
 * inline-editable form fields. This is the component `UsbTopologyTree`
 * moves focus to on Enter/Space (architecture §9.4).
 */
const props = defineProps<{ device: DeviceStatus }>()

const emit = defineEmits<{ 'request-serial-flash': [deviceId: string] }>()

const fleetStore = useFleetStore()

const stateMeta = computed(() => DEVICE_STATE_META[props.device.state as DeviceState])

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

function commitName(name: string): void {
  void fleetStore.patchDevice(props.device.device_id, { name })
}

function commitPort(port: number): void {
  void fleetStore.patchDevice(props.device.device_id, { output_port: port })
}

function commitEnabled(enabled: boolean): void {
  void fleetStore.patchDevice(props.device.device_id, { enabled })
}

const isEditable = computed(() => !props.device.needs_identification)
const ownReservedPorts = computed(() =>
  props.device.output ? [props.device.output.iq_port, props.device.output.control_port] : [],
)
</script>

<template>
  <article
    :id="`device-card-${device.device_id}`"
    tabindex="-1"
    class="flex flex-col gap-3 border-b border-ground-hairline bg-ground-panel px-4 py-4 first:rounded-t-rack last:rounded-b-rack"
    :class="`border-l-[3px] ${stateMeta.borderColorClass}`"
  >
    <header class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <h3 class="font-condensed text-base font-semibold uppercase tracking-legend">
          {{ device.name || device.device_id }}
        </h3>
        <DeviceStatusBadge :state="device.state as DeviceState" :reason="device.state_reason" />
      </div>
      <BaseToggle
        v-if="device.record_id !== null"
        :model-value="device.enabled"
        :label="`Enabled — ${device.name || device.device_id}`"
        @update:model-value="commitEnabled"
      />
    </header>

    <NeedsIdentificationNotice
      v-if="device.needs_identification"
      @request-serial-flash="emit('request-serial-flash', device.device_id)"
    />
    <DeviceAbsentNotice
      v-else-if="!device.present"
      :last-topology-path="device.usb_last_known?.topology_path ?? null"
    />

    <div class="flex flex-wrap items-center gap-4">
      <JackPair
        :iq-port="device.output?.iq_port ?? null"
        :control-port="device.output?.control_port ?? null"
      />
      <dl v-if="device.tuner" class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-signal-slate">
        <div class="flex gap-1">
          <dt>Center</dt>
          <dd><MonoValue :value="(device.tuner.center_hz / 1_000_000).toFixed(3)" unit="MHz" /></dd>
        </div>
        <div class="flex gap-1">
          <dt>Rate</dt>
          <dd><MonoValue :value="(device.tuner.sample_rate / 1_000).toFixed(0)" unit="kS/s" /></dd>
        </div>
        <div class="flex gap-1">
          <dt>Gain</dt>
          <dd>
            <!-- No unit when the tuner is in AGC: the value is a mode, not a
                 measurement, and "AGC dB" reads as nonsense. -->
            <MonoValue v-if="device.tuner.gain_auto" value="AGC" />
            <MonoValue v-else :value="device.tuner.gain_db.toFixed(1)" unit="dB" />
          </dd>
        </div>
      </dl>
    </div>

    <div v-if="isEditable" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <DeviceNameField v-model="nameDraft" @commit="commitName" />
      <PortAssignmentField
        v-model="portDraft"
        :constraints="fleetStore.constraints"
        :own-reserved-ports="ownReservedPorts"
        :committed-iq-port="device.output?.iq_port ?? null"
        @commit="commitPort"
      />
    </div>
  </article>
</template>
