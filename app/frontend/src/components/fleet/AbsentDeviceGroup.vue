<script setup lang="ts">
import type { DeviceStatus } from '@/api/client'
import SdrDeviceCard from '@/components/device/SdrDeviceCard.vue'

/**
 * Collapsible, visually de-emphasised group for configured devices that are
 * not currently plugged in ("ghosts" — Sentry keys unidentified dongles by
 * USB topology path, so a re-enumerated or moved dongle leaves its old
 * configuration behind as an absent record). Kept structurally separate from
 * the present-device stack, with a dashed border and its own disclosure
 * rather than colour alone, so an operator scanning the page can tell
 * instantly what hardware is actually attached — and collapsed by default so
 * several accumulated ghosts never dominate the page.
 */
defineProps<{ devices: DeviceStatus[] }>()
defineEmits<{
  'request-serial-flash': [deviceId: string]
  'request-forget-device': [deviceId: string]
}>()
</script>

<template>
  <details class="mt-4 rounded-rack border border-dashed border-signal-slateMuted/60">
    <summary
      class="flex min-h-[44px] cursor-pointer list-none items-center gap-2 rounded-rack px-4 py-2 font-condensed text-xs uppercase tracking-legend text-signal-slate [&::-webkit-details-marker]:hidden"
    >
      <span aria-hidden="true">▽</span>
      Absent devices — configuration kept ({{ devices.length }})
    </summary>
    <p
      class="border-t border-dashed border-signal-slateMuted/60 px-4 py-2 text-xs text-signal-slate"
    >
      Not currently plugged in. Replugging the hardware re-detects it; forgetting one discards its
      saved name, port and tuning defaults.
    </p>
    <div class="flex flex-col border-t border-dashed border-signal-slateMuted/60">
      <SdrDeviceCard
        v-for="device in devices"
        :key="device.device_id"
        :device="device"
        @request-serial-flash="$emit('request-serial-flash', $event)"
        @request-forget-device="$emit('request-forget-device', $event)"
      />
    </div>
  </details>
</template>
