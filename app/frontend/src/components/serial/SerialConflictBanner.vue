<script setup lang="ts">
import BaseButton from '@/components/base/BaseButton.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'

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
  <NoticeBox tone="danger" role="alert">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <div class="flex flex-col gap-3">
        <p class="m-0">
          Serial conflict — <span class="font-mono">{{ serial }}</span> is reported by more than one
          present device<span v-if="conflictingDevices.length">
            ({{ conflictingDevices.map((device) => device.label).join(', ') }})</span
          >. Neither can be remembered across a reboot until one is given a unique serial.
        </p>
        <ul v-if="conflictingDevices.length" class="m-0 flex list-none flex-wrap gap-2 p-0">
          <li v-for="device in conflictingDevices" :key="device.deviceId">
            <BaseButton variant="ghost" @click="$emit('request-serial-flash', device.deviceId)">
              Flash serial — {{ device.label }}
            </BaseButton>
          </li>
        </ul>
      </div>
      <BaseButton variant="ghost" class="shrink-0 self-start" @click="$emit('dismiss')">
        Dismiss
        <span class="sr-only">serial conflict for {{ serial }}</span>
      </BaseButton>
    </div>
  </NoticeBox>
</template>
