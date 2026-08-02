<script setup lang="ts">
/**
 * A top-level section title in Sentinel's settings style
 * (`#settings-section-heading`): large uppercase Barlow with wide tracking,
 * preceded by a small accent dot that echoes the wordmark's mark. The dot is
 * decorative — the heading text alone is what assistive tech announces.
 *
 * `level` picks the heading element so the page keeps a correct outline
 * without the caller having to restate the visual treatment; the look is
 * identical at every level, because in a settings-style layout the group
 * label beneath (`GroupLabel`) carries the visual step down, not the heading.
 */
withDefaults(
  defineProps<{
    /** Heading level, 1-3. Defaults to `2`. */
    level?: 1 | 2 | 3
    /** Tone of the accent dot. Defaults to the amber identity accent. */
    dotClass?: string
  }>(),
  { level: 2, dotClass: 'bg-signal-accent' },
)
</script>

<template>
  <component
    :is="`h${level}`"
    class="flex items-center gap-3 font-sans text-[21px] font-normal uppercase leading-none tracking-heading text-ink-primary"
  >
    <span aria-hidden="true" class="h-1.5 w-1.5 shrink-0 rounded-full" :class="dotClass" />
    <slot />
  </component>
</template>
