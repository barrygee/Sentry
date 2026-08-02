<script setup lang="ts">
/**
 * The rack-blank-plate empty state (architecture §9.5): terse, no
 * illustration, no marketing tone.
 *
 * Sentinel's `.settings-empty` is bare text on the canvas with no container
 * at all. Sentry keeps a dashed panel around it, because unlike a settings
 * section that is simply empty, "no devices detected" is a state an operator
 * needs to see occupying the slot where hardware would be.
 */
withDefaults(defineProps<{ title: string; detail?: string | null }>(), { detail: null })
</script>

<template>
  <div
    class="flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-rack bg-ground-panel px-6 py-10 text-center"
  >
    <p class="font-sans text-[9px] uppercase tracking-control text-signal-muted">
      {{ title }}
    </p>
    <p v-if="detail" class="max-w-prose text-[12px] leading-[1.6] text-signal-muted">
      {{ detail }}
    </p>
  </div>
</template>
