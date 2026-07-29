<script setup lang="ts">
/**
 * The small port-lug marker drawn at each junction of the topology tree's
 * signal-chain connector, carrying the physical hub port number (decorative
 * — the tree node's accessible name already states the full USB path).
 *
 * Amber, matching `JackPair`: both are physical-connector motifs and share
 * the app's primary identity accent (architecture §9.5).
 */
defineProps<{ portNumber: number }>()
</script>

<template>
  <span
    aria-hidden="true"
    class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-[1px] border border-signal-amber/60 bg-ground-raised font-mono text-[9px] font-mono-tabular text-signal-amber"
  >
    {{ portNumber }}
  </span>
</template>
