<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { DeviceStatus } from '@/api/client'
import BaseToggle from '@/components/base/BaseToggle.vue'
import DataCell from '@/components/base/DataCell.vue'
import MonoValue from '@/components/base/MonoValue.vue'
import DeviceAntennaField from '@/components/forms/DeviceAntennaField.vue'
import DeviceNameField from '@/components/forms/DeviceNameField.vue'
import DeviceNotesField from '@/components/forms/DeviceNotesField.vue'
import PortAssignmentField from '@/components/forms/PortAssignmentField.vue'
import { useFleetStore } from '@/stores/fleet'

import DeviceAbsentNotice from './DeviceAbsentNotice.vue'
import DeviceStatusBadge from './DeviceStatusBadge.vue'
import DeviceVisibilityToggle from './DeviceVisibilityToggle.vue'
import NeedsIdentificationNotice from './NeedsIdentificationNotice.vue'

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
const props = defineProps<{ device: DeviceStatus }>()

const emit = defineEmits<{
  'request-serial-flash': [deviceId: string]
}>()

const fleetStore = useFleetStore()

const nameDraft = ref(props.device.name)
const portDraft = ref<number | null>(props.device.output?.iq_port ?? null)
const antennaDraft = ref(props.device.antenna)
const notesDraft = ref(props.device.notes)

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
watch(
  () => props.device.antenna,
  (nextAntenna) => {
    if (fleetStore.pendingPatchesByDeviceId[props.device.device_id] === undefined) {
      antennaDraft.value = nextAntenna
    }
  },
)
watch(
  () => props.device.notes,
  (nextNotes) => {
    if (fleetStore.pendingPatchesByDeviceId[props.device.device_id] === undefined) {
      notesDraft.value = nextNotes
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

function commitVisibility(visibility: 'public' | 'private'): void {
  void fleetStore.patchDevice(props.device.device_id, { visibility })
}

// Antenna and notes are only ever offered on a device that already has a
// persisted row, so — unlike name and port — they never need the combined
// first-configuration PATCH above and can always be committed alone.
function commitAntenna(antenna: string): void {
  void fleetStore.patchDevice(props.device.device_id, { antenna })
}

function commitNotes(notes: string): void {
  void fleetStore.patchDevice(props.device.device_id, { notes })
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
  <article
    :id="`device-card-${device.device_id}`"
    tabindex="-1"
    class="flex flex-col gap-6 rounded-rack bg-ground-panel p-card outline-none"
  >
    <!-- Row 1 — identity and the one control that changes what the device is
         doing right now. -->
    <div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      <div class="flex flex-wrap items-center gap-3">
        <h3 class="sr-only">{{ device.name || device.device_id }}</h3>
        <DeviceStatusBadge :state="device.state" :reason="device.state_reason ?? null" />
      </div>
      <!-- Both switches sit together on the right: one controls whether the
           device runs, the other whether anyone else is told about it. -->
      <div v-if="device.record_id !== null" class="flex flex-wrap items-center gap-x-6 gap-y-2">
        <DeviceVisibilityToggle :device="device" @commit="commitVisibility" />
        <BaseToggle
          :model-value="device.enabled"
          :label="device.enabled ? 'Disable SDR' : 'Enable SDR'"
          :accessible-name="`${device.enabled ? 'Disable SDR' : 'Enable SDR'} — ${device.name || device.device_id}`"
          @update:model-value="commitEnabled"
        />
      </div>
    </div>

    <NeedsIdentificationNotice
      v-if="device.needs_identification"
      @request-serial-flash="emit('request-serial-flash', device.device_id)"
    />
    <DeviceAbsentNotice
      v-else-if="!device.present"
      :last-topology-path="device.usb_last_known?.topology_path ?? null"
    />

    <!-- Rows 2 and 3 share one grid, so their columns line up: "Output port"
         sits above "Serial number", "Relay listens on" above "Center
         frequency". As two independent flex rows each column landed wherever
         its own content ended, and nothing aligned between them.

         Tracks are `max-content` rather than equal fractions — a model string
         is far wider than a gain reading, and equal columns would have wrapped
         the long one to make room for whitespace beside the short one. The
         count steps down at narrower widths rather than overflowing. -->
    <div
      class="grid grid-cols-[repeat(2,max-content)] items-start gap-x-8 gap-y-5 sm:grid-cols-[repeat(3,max-content)] lg:grid-cols-[repeat(5,max-content)]"
    >
      <template v-if="isEditable">
        <DeviceNameField v-model="nameDraft" class="w-[160px]" @commit="commitName" />
        <PortAssignmentField
          v-model="portDraft"
          :constraints="fleetStore.constraints"
          :own-reserved-ports="ownReservedPorts"
          @commit="commitPort"
        />
        <p
          v-if="needsBothFieldsToConfigure"
          class="col-span-full m-0 text-[12.5px] leading-[1.55] text-signal-muted"
        >
          Configuring a new device needs both a valid name and a valid output port — nothing is
          saved until both fields have been entered.
        </p>
      </template>

      <!-- `col-start-1` starts the read-only band on a fresh row instead of
           flowing into whatever column the fields above left free. -->
      <dl class="contents">
        <DataCell
          class="col-start-1"
          label="Model"
          label-tag="dt"
          value-tag="dd"
          :value="identityModel"
        />
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
    </div>

    <!-- Antenna and notes each get their own line below the aligned grid,
         rather than a track inside it. Antenna follows the read-only band
         (…rate, gain) so the tuning story reads in one block and the two
         operator-written fields sit together underneath it; notes needs the
         whole card width, which a `max-content` track cannot give it.
         Only offered once a row exists — a lone antenna or notes PATCH on an
         unconfigured device would be rejected, since a first configuration
         must carry both name and port together. -->
    <template v-if="isEditable && device.record_id !== null">
      <DeviceAntennaField v-model="antennaDraft" class="w-[240px]" @commit="commitAntenna" />
      <DeviceNotesField v-model="notesDraft" @commit="commitNotes" />
    </template>
  </article>
</template>
