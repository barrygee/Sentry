<script setup lang="ts">
/**
 * The rack-blank-plate empty state (architecture §9.5): terse, no
 * illustration, no marketing tone.
 */
withDefaults(defineProps<{ title: string; detail?: string | null }>(), { detail: null })
</script>

<template>
  <div
    class="flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-rack border border-dashed border-ground-hairline bg-ground-panel px-6 py-10 text-center"
  >
    <p class="font-condensed text-sm uppercase tracking-legend text-signal-slate">{{ title }}</p>
    <p v-if="detail" class="max-w-prose text-xs text-signal-slate">{{ detail }}</p>
  </div>
</template>
