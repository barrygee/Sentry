<script setup lang="ts">
import MonoValue from '@/components/base/MonoValue.vue'

/**
 * The signature "Patch Bay" element (architecture §9.5): the IQ port `P`
 * and control port `P+2` rendered as a pair of etched jacks. Appears on the
 * device card, in the topology lug, and on the Sentinel-endpoint card —
 * this is the one component all three compose rather than duplicate.
 *
 * Labelled in signal-amber, not cyan: this is the app's primary identity
 * accent (architecture §9.5) and this is its most-repeated element, so it
 * carries the bulk of amber's on-screen presence. Cyan remains reserved for
 * secondary/structural chrome (the topology tree's connector lines and
 * section heading) so the palette still reads as two colours, not one.
 */
withDefaults(
  defineProps<{
    iqPort: number | null
    controlPort: number | null
    compact?: boolean
  }>(),
  { compact: false },
)
</script>

<template>
  <dl class="flex items-stretch gap-px overflow-hidden rounded-rack border border-ground-hairline">
    <div
      class="flex flex-col items-center bg-ground-raised px-3 py-1.5"
      :class="compact ? 'px-2 py-1' : ''"
    >
      <dt
        class="font-condensed text-[10px] uppercase tracking-legend text-signal-amber"
        aria-hidden="true"
      >
        IQ
      </dt>
      <dd class="text-sm">
        <MonoValue :value="iqPort ?? '—'" />
        <span class="sr-only">IQ port</span>
      </dd>
    </div>
    <div
      class="flex flex-col items-center bg-ground-raised px-3 py-1.5"
      :class="compact ? 'px-2 py-1' : ''"
    >
      <dt
        class="font-condensed text-[10px] uppercase tracking-legend text-signal-amber"
        aria-hidden="true"
      >
        CTRL
      </dt>
      <dd class="text-sm">
        <MonoValue :value="controlPort ?? '—'" />
        <span class="sr-only">control port</span>
      </dd>
    </div>
  </dl>
</template>
