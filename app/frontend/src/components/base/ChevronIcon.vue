<script setup lang="ts">
/**
 * Sentinel's disclosure chevron (`ChevronIcon` / `.bfp-item-chevron`), drawn
 * at the same 10px box with the same 1.3 round-capped stroke so a Sentry
 * accordion and a Sentinel side-panel accordion carry the identical mark.
 *
 * Points right when closed and down when open — Sentinel's own `rotate(-90deg)`
 * → `rotate(0deg)` transition, not a swapped glyph, so the arrow turns rather
 * than blinking from one character to another.
 *
 * Inherits `currentColor`, which is what lets the summary that hosts it drive
 * the colour: dim by default, brightening with the label on hover and while
 * open, exactly as Sentinel's does.
 */
withDefaults(defineProps<{ open?: boolean; strokeWidth?: number }>(), {
  open: false,
  strokeWidth: 1.3,
})
</script>

<template>
  <svg
    width="10"
    height="10"
    viewBox="0 0 10 10"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    class="block shrink-0 transition-transform duration-200 ease-out motion-reduce:transition-none"
    :class="open ? 'rotate-0' : '-rotate-90'"
  >
    <path
      d="M2 3.5L5 6.5L8 3.5"
      stroke="currentColor"
      :stroke-width="strokeWidth"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>
