<script setup lang="ts">
/**
 * The muted, wide-tracked subsection label that divides a card grid
 * (Sentinel `.settings-group-label` — "ALERTS", "DATA SOURCES", …). Spans the
 * full grid row so the cards beneath it read as one band.
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
    class="col-span-full m-0 font-sans text-[10px] uppercase tracking-group text-signal-muted"
  >
    <slot />
  </component>
</template>
