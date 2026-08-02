<script setup lang="ts">
/**
 * The band label above a section, in Sentinel's section-title treatment
 * (`.sdr-ef-settings-toggle-title`): 9px Barlow 700, uppercase, 0.18em, white.
 * The same step its own CONTROLS/SETTINGS headings use.
 *
 * Rendered as a real heading by default so the grid beneath it is reachable
 * as a section by screen-reader users; pass `level="none"` for a purely
 * decorative divider whose content is already announced elsewhere.
 */
withDefaults(
  defineProps<{
    /** Heading level, or `'none'` for a plain `<p>`. Defaults to `3`. */
    level?: 2 | 3 | 4 | 'none'
  }>(),
  { level: 3 },
)
</script>

<template>
  <component
    :is="level === 'none' ? 'p' : `h${level}`"
    class="m-0 font-sans text-[9px] font-bold uppercase tracking-control text-white"
  >
    <slot />
  </component>
</template>
