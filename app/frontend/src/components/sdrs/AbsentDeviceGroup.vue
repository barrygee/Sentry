<script setup lang="ts">
import { ref } from 'vue'

import type { DeviceStatus } from '@/api/client'
import ChevronIcon from '@/components/base/ChevronIcon.vue'
import PanelStack from '@/components/base/PanelStack.vue'
import SdrDeviceCard from '@/components/device/SdrDeviceCard.vue'

/**
 * Collapsible, visually de-emphasised group for configured devices that are
 * not currently plugged in ("ghosts" — Sentry keys unidentified dongles by
 * USB topology path, so a re-enumerated or moved dongle leaves its old
 * configuration behind as an absent record). Kept structurally separate from
 * the present-device stack, behind its own disclosure rather than colour
 * alone, so an operator scanning the page can tell instantly what hardware is
 * actually attached — and collapsed by default so several accumulated ghosts
 * never dominate the page.
 *
 * The group has no fill of its own. It carried a faint wash (which replaced
 * an earlier dashed outline), but a tinted container wrapping white device
 * boxes only banded the canvas above and below them — reading as a stray
 * panel edge rather than as a group. De-emphasis comes entirely from the
 * muted summary and description, and from the disclosure being closed by
 * default.
 *
 * The summary sits on the settings vocabulary: a muted group label (matching
 * "USB Topology" and "Devices" above it), with the ghosts inside laid out in
 * their own `PanelStack`, so an expanded group looks like the live grid with
 * the colour drained out of it rather than like a different kind of list.
 */
defineProps<{ devices: DeviceStatus[] }>()
defineEmits<{
  'request-serial-flash': [deviceId: string]
}>()

// `<details open>` is a DOM attribute the browser toggles itself, so it is
// mirrored here off the element's own `toggle` event rather than bound with
// `v-model`. That keeps the native disclosure behaviour (including keyboard
// and find-in-page expansion) authoritative, with the chevron following it.
const isOpen = ref(false)

function syncOpenState(event: Event): void {
  isOpen.value = (event.target as HTMLDetailsElement).open
}
</script>

<template>
  <details class="group mt-2 rounded-rack" @toggle="syncOpenState">
    <!-- No horizontal padding anywhere in this group: the label, the
         description and the boxes below all start at the same left edge as
         every other device box on the page. Both the label and the description
         previously carried the cards' own `px-card` inset, which set them 30px
         in from the column everything else lines up against.

         The chevron is pinned right by `ml-auto`, landing on the boxes' right
         edge — Sentinel's side-panel accordion row (`.bfp-item-chevron`). -->
    <summary
      class="flex min-h-[44px] cursor-pointer list-none items-center gap-2 rounded-rack py-3 font-sans text-[10px] font-semibold uppercase tracking-control text-signal-muted transition-colors hover:text-ink-primary [&::-webkit-details-marker]:hidden"
    >
      Absent devices — configuration kept ({{ devices.length }})
      <ChevronIcon class="ml-auto" :open="isOpen" />
    </summary>
    <div class="flex flex-col gap-4 pb-card">
      <p class="m-0 text-[12.5px] leading-[1.55] text-signal-muted">
        Not currently plugged in. Replugging the hardware re-detects it; forgetting one discards its
        saved name, port and tuning defaults.
      </p>
      <PanelStack>
        <SdrDeviceCard
          v-for="device in devices"
          :key="device.device_id"
          :device="device"
          @request-serial-flash="$emit('request-serial-flash', $event)"
        />
      </PanelStack>
    </div>
  </details>
</template>
