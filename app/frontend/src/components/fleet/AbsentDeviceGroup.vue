<script setup lang="ts">
import type { DeviceStatus } from '@/api/client'
import PanelGrid from '@/components/base/PanelGrid.vue'
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
 *
 * The dashed container and its summary now sit on the settings vocabulary:
 * the summary reads as a muted group label (matching "USB Topology" and
 * "Devices" above it) and the ghosts inside lay out in their own `PanelGrid`,
 * so an expanded group looks like the live grid with the colour drained out
 * of it rather than like a different kind of list.
 */
defineProps<{ devices: DeviceStatus[] }>()
defineEmits<{
  'request-serial-flash': [deviceId: string]
  'request-forget-device': [deviceId: string]
}>()
</script>

<template>
  <details class="group mt-2 rounded-rack border border-dashed border-signal-faint/60">
    <summary
      class="flex min-h-[44px] cursor-pointer list-none items-center gap-2 rounded-rack px-card py-3 font-condensed text-[10px] font-semibold uppercase tracking-group text-signal-muted transition-colors hover:text-ink-primary [&::-webkit-details-marker]:hidden"
    >
      <span aria-hidden="true" class="transition-transform group-open:rotate-90">▶</span>
      Absent devices — configuration kept ({{ devices.length }})
    </summary>
    <div class="flex flex-col gap-4 border-t border-dashed border-signal-faint/60 p-card">
      <p class="m-0 text-[12.5px] leading-[1.55] text-signal-muted">
        Not currently plugged in. Replugging the hardware re-detects it; forgetting one discards its
        saved name, port and tuning defaults.
      </p>
      <PanelGrid>
        <SdrDeviceCard
          v-for="device in devices"
          :key="device.device_id"
          :device="device"
          @request-serial-flash="$emit('request-serial-flash', $event)"
          @request-forget-device="$emit('request-forget-device', $event)"
        />
      </PanelGrid>
    </div>
  </details>
</template>
