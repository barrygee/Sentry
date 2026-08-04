<script setup lang="ts">
/**
 * A dialog or section title, in Sentinel's condensed-title style — the same
 * treatment it gives a station name (`Barlow Condensed`, uppercase, lightly
 * tracked) rather than the 9px legends it uses for section labels, which are
 * far too small to head a modal.
 *
 * `level` picks the heading element so the page keeps a correct outline
 * without the caller restating the visual treatment.
 *
 * There is no accent dot. An earlier version prefixed every heading with one,
 * echoing the wordmark's mark; the mark now appears once, in `SdrsHeader`,
 * where it means something.
 */
withDefaults(
  defineProps<{
    /** Heading level, 1-3. Defaults to `2`. */
    level?: 1 | 2 | 3
  }>(),
  { level: 2 },
)
</script>

<template>
  <component
    :is="`h${level}`"
    class="m-0 font-condensed text-[18px] font-normal uppercase leading-tight tracking-readout text-ink-primary"
  >
    <slot />
  </component>
</template>
