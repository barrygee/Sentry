<script setup lang="ts">
/**
 * Tabular-figure numeric/mono display — the shared atom for every port,
 * frequency, PID, USB path and byte count so digits never shift width as
 * they tick (architecture §9.5 typography).
 */
withDefaults(
  defineProps<{
    value: string | number
    unit?: string | null
  }>(),
  { unit: null },
)
</script>

<template>
  <span class="font-mono font-mono-tabular text-[#e7e9ea]">
    {{ value }}<span v-if="unit" class="ml-0.5 text-signal-slate">{{ unit }}</span>
  </span>
</template>
