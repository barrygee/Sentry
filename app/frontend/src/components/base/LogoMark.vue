<script setup lang="ts">
/**
 * The ⊙ mark, identical to Sentinel's — a white ring with a lime centre dot.
 *
 * Proportions are taken straight from Sentinel's `assets/logo.svg` and kept as
 * ratios of its 34.90 artboard, so the mark scales to any size without
 * drifting from the original:
 *   ring radius 14.41, stroke 4.08, dot radius 5.69, all about centre 17.4497.
 *
 * Decorative: the wordmark beside it already names the app, so this carries
 * `aria-hidden` and no title. `size` is in px and drives everything.
 */
withDefaults(defineProps<{ size?: number }>(), { size: 26 })

/** Sentinel's logo.svg artboard height — the basis every ratio below is expressed against. */
const SENTINEL_ARTBOARD = 34.9
const CENTRE = 17.449658203125
const RING_RADIUS = 14.41
const RING_STROKE = 4.08
const DOT_RADIUS = 5.69
</script>

<template>
  <svg
    :width="size"
    :height="size"
    :viewBox="`0 0 ${SENTINEL_ARTBOARD} ${SENTINEL_ARTBOARD}`"
    aria-hidden="true"
    focusable="false"
    class="shrink-0"
  >
    <circle
      :cx="CENTRE"
      :cy="CENTRE"
      :r="RING_RADIUS"
      fill="none"
      stroke="#ffffff"
      :stroke-width="RING_STROKE"
    />
    <circle :cx="CENTRE" :cy="CENTRE" :r="DOT_RADIUS" fill="#c8ff00" />
  </svg>
</template>
