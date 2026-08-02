<script setup lang="ts">
/**
 * The small port-lug marker drawn at each junction of the topology tree's
 * signal-chain connector, carrying the physical hub port number (decorative
 * — the tree node's accessible name already states the full USB path).
 *
 * Neutral, not accent-coloured. The accent can only ever be a solid fill
 * (1.18:1 as text — see `tailwind.config.ts`), and a solid lime chip repeated
 * at every node turns the tree into a row of highlighter marks. Sentinel is
 * disciplined about this: across its whole settings panel the accent appears
 * only on the heading dot and the commit button, and every small marker like
 * this one is a plain grey fill. Sentry follows suit.
 */
defineProps<{ portNumber: number }>()
</script>

<template>
  <span
    aria-hidden="true"
    class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-rack bg-ground-raised text-[9px] font-tabular text-signal-muted"
  >
    {{ portNumber }}
  </span>
</template>
