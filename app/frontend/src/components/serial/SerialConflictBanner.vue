<script setup lang="ts">
import BaseButton from '@/components/base/BaseButton.vue'

/**
 * Surfaces a duplicate-serial conflict (architecture §5.1 tier 3, and the
 * `409 serial_in_use` guard on the EEPROM flash flow §7.6): two present
 * devices report the same serial, so neither can be trusted as a
 * persistence key until the operator flashes a unique one.
 *
 * This is the fleet-level summary of the same condition
 * `NeedsIdentificationNotice` already surfaces inline on each affected
 * card — one banner per duplicate serial, offering the destructive action
 * directly against whichever of the conflicting devices the operator
 * chooses to re-identify.
 */
withDefaults(
  defineProps<{
    serial: string
    conflictingDevices: { deviceId: string; label: string }[]
  }>(),
  { conflictingDevices: () => [] },
)

defineEmits<{ dismiss: []; 'request-serial-flash': [deviceId: string] }>()
</script>

<template>
  <div
    role="alert"
    class="flex flex-col gap-2 rounded-rack border border-signal-red bg-signal-red/10 px-3 py-2 text-xs text-signal-red sm:flex-row sm:items-start sm:justify-between sm:gap-3"
  >
    <div class="flex flex-col gap-2">
      <p>
        Serial conflict — <span class="font-mono">{{ serial }}</span> is reported by more than one
        present device<span v-if="conflictingDevices.length">
          ({{ conflictingDevices.map((device) => device.label).join(', ') }})</span
        >. Neither can be remembered across a reboot until one is given a unique serial.
      </p>
      <ul v-if="conflictingDevices.length" class="flex flex-wrap gap-2">
        <li v-for="device in conflictingDevices" :key="device.deviceId">
          <BaseButton variant="ghost" @click="$emit('request-serial-flash', device.deviceId)">
            Flash serial — {{ device.label }}
          </BaseButton>
        </li>
      </ul>
    </div>
    <button
      type="button"
      class="min-h-[44px] shrink-0 rounded-rack border border-signal-red px-2 font-condensed text-xs uppercase tracking-legend"
      @click="$emit('dismiss')"
    >
      Dismiss
    </button>
  </div>
</template>
