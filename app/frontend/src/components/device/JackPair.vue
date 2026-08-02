<script setup lang="ts">
import MonoValue from '@/components/base/MonoValue.vue'

/**
 * The signature "Patch Bay" element (architecture §9.5): the IQ port `P`
 * and control port `P+2` rendered as a pair of etched jacks. Appears on the
 * device card, in the topology lug, and on the Sentinel-endpoint card —
 * this is the one component all three compose rather than duplicate.
 *
 * The IQ/CTRL legends are neutral, not accent-coloured. On the light theme
 * the accent is fill-only (1.18:1 as text), and an accent *fill* behind two
 * legends repeated on every card would shout — so these follow Sentinel's own
 * treatment of the same element, `.settings-location-label`, which keeps its
 * inline legend a plain muted grey and lets the accent live on controls.
 * `PortLug` carries the accent in the topology tree instead.
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
  <!-- Sentinel's labelled-input shell turned into a readout: one flat, square
       surface split by hairline gaps, the legend inside the fill rather than
       floating above it. -->
  <dl class="m-0 flex items-stretch gap-px overflow-hidden rounded-rack bg-ground-hairline">
    <div
      class="flex flex-col items-center bg-ground-raised px-3 py-1.5"
      :class="compact ? 'px-2 py-1' : ''"
    >
      <dt
        class="font-sans text-[9px] uppercase tracking-heading text-signal-muted"
        aria-hidden="true"
      >
        IQ
      </dt>
      <dd class="m-0 text-sm">
        <span class="sr-only">IQ port </span><MonoValue :value="iqPort ?? '—'" />
      </dd>
    </div>
    <div
      class="flex flex-col items-center bg-ground-raised px-3 py-1.5"
      :class="compact ? 'px-2 py-1' : ''"
    >
      <dt
        class="font-sans text-[9px] uppercase tracking-heading text-signal-muted"
        aria-hidden="true"
      >
        CTRL
      </dt>
      <dd class="m-0 text-sm">
        <span class="sr-only">control port </span><MonoValue :value="controlPort ?? '—'" />
      </dd>
    </div>
  </dl>
</template>
