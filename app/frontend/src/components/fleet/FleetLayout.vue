<script setup lang="ts">
import { ref } from 'vue'

/**
 * The two-column rack shell (architecture §9.5 layout). Mobile-first: below
 * `md` the topology tree collapses into a disclosure above the device
 * stack; at `md` and up it becomes a fixed-width left rail running
 * alongside the stack. One DOM instance of the topology slot content is
 * rendered regardless of breakpoint — only its container's visibility
 * changes — so roving-tabindex focus state and element ids never duplicate.
 */
const isTopologyExpandedOnMobile = ref(true)

function toggleTopology(): void {
  isTopologyExpandedOnMobile.value = !isTopologyExpandedOnMobile.value
}
</script>

<template>
  <div
    class="flex flex-1 flex-col gap-4 p-4 sm:p-6 md:grid md:grid-cols-[320px_1fr] md:items-start"
  >
    <section aria-labelledby="topology-heading" class="flex flex-col gap-2 md:sticky md:top-4">
      <div class="flex items-center justify-between">
        <h2
          id="topology-heading"
          class="font-condensed text-xs font-semibold uppercase tracking-legend text-signal-cyan"
        >
          USB Topology
        </h2>
        <button
          type="button"
          class="min-h-[44px] rounded-rack px-2 font-condensed text-xs uppercase tracking-legend text-signal-slate md:hidden"
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

    <section aria-labelledby="devices-heading" class="flex flex-col">
      <h2 id="devices-heading" tabindex="-1" class="sr-only outline-none">Devices</h2>
      <slot name="devices" />
    </section>
  </div>
</template>
