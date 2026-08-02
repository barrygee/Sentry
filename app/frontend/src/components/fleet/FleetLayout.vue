<script setup lang="ts">
import { ref } from 'vue'

import GroupLabel from '@/components/base/GroupLabel.vue'

/**
 * The two-column rack shell (architecture §9.5 layout), laid out on
 * Sentinel's settings-body gutters: 44px of page padding at `md` and up, a
 * generous bottom gutter so the last card never sits flush against the
 * viewport edge, and a 16px gap matching the card grid's own.
 *
 * Mobile-first: below `md` the topology tree collapses into a disclosure
 * above the device stack; at `md` and up it becomes a fixed-width left rail
 * running alongside the stack. One DOM instance of the topology slot content
 * is rendered regardless of breakpoint — only its container's visibility
 * changes — so roving-tabindex focus state and element ids never duplicate.
 *
 * Both column headings use the muted group-label style rather than a second
 * large heading: in the settings vocabulary a page carries exactly one 21px
 * title (the wordmark in `FleetHeader`) and everything below it is a band
 * label. "Devices" was previously visually hidden — now that the band labels
 * are part of the look it is visible, which also gives the skip link a
 * destination the operator can actually see land.
 */
const isTopologyExpandedOnMobile = ref(true)

function toggleTopology(): void {
  isTopologyExpandedOnMobile.value = !isTopologyExpandedOnMobile.value
}
</script>

<template>
  <div
    class="flex flex-1 flex-col gap-6 px-5 pb-16 pt-[26px] md:grid md:grid-cols-[320px_1fr] md:items-start md:gap-4 md:px-gutter md:pb-[110px]"
  >
    <section aria-labelledby="topology-heading" class="flex flex-col gap-3 md:sticky md:top-4">
      <div class="flex items-center justify-between gap-2">
        <GroupLabel id="topology-heading" :level="2">USB Topology</GroupLabel>
        <button
          type="button"
          class="-my-2 min-h-[44px] rounded-rack px-2 font-sans text-[10px] uppercase tracking-control text-signal-muted transition-colors hover:text-ink-primary md:hidden"
          :aria-expanded="isTopologyExpandedOnMobile"
          aria-controls="topology-panel"
          @click="toggleTopology"
        >
          {{ isTopologyExpandedOnMobile ? 'Hide' : 'Show' }}
        </button>
      </div>
      <div id="topology-panel" :class="[isTopologyExpandedOnMobile ? '' : 'hidden', 'md:block']">
        <slot name="topology" />
      </div>
    </section>

    <section aria-labelledby="devices-heading" class="flex flex-col gap-3">
      <GroupLabel id="devices-heading" :level="2" tabindex="-1" class="outline-none">
        Devices
      </GroupLabel>
      <slot name="devices" />
    </section>
  </div>
</template>
