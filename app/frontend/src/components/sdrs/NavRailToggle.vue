<script setup lang="ts">
/**
 * The rail's show/hide control, matching Sentinel's footer side-panel button
 * (`#map-sidebar-btn`): a 36px-tall, rail-width icon button at 60% opacity,
 * brightening to full on hover.
 *
 * It has a fill only while the rail is shown — the rail's own dark tone, so
 * the button is indistinguishable from the column it sits at the foot of.
 * Once the rail is hidden the fill goes with it and the glyph sits directly on
 * the page canvas, which means it also has to invert: a white mark would
 * disappear on that light ground, so it switches to `ink.primary` (4.2:1 at
 * this opacity, clearing the 3:1 a non-text mark needs).
 *
 * It is positioned by its parent (`App.vue`) rather than living inside
 * `NavRail`, because it has to survive the rail being hidden; see that file.
 *
 * The glyph is Sentinel's panel mark — a rounded rectangle with a rule down
 * its left — drawn at the same 14px and 1.1 stroke, so the two apps' toggles
 * are the same control rather than two drawings of one idea.
 */
defineProps<{
  /** Whether the rail is currently shown. */
  expanded: boolean
  /** The id of the element this button shows and hides. */
  controls: string
}>()

defineEmits<{ toggle: [] }>()
</script>

<template>
  <button
    type="button"
    class="flex h-9 w-12 shrink-0 items-center justify-center opacity-60 transition-opacity hover:opacity-100"
    :class="expanded ? 'bg-ground-rail text-ink-inverse' : 'text-ink-primary'"
    :aria-expanded="expanded"
    :aria-controls="controls"
    :aria-label="expanded ? 'Hide sidebar' : 'Show sidebar'"
    :title="expanded ? 'Hide sidebar' : 'Show sidebar'"
    @click="$emit('toggle')"
  >
    <svg
      width="14"
      height="14"
      viewBox="0 0 15 15"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect
        x="1.5"
        y="1.5"
        width="12"
        height="12"
        rx="1"
        stroke="currentColor"
        stroke-width="1.1"
      />
      <line x1="5.5" y1="1.5" x2="5.5" y2="13.5" stroke="currentColor" stroke-width="1.1" />
    </svg>
  </button>
</template>
