<script setup lang="ts">
/**
 * The card grid every settings-style section lays out in (Sentinel
 * `.settings-grid`): columns auto-fill at a 300px minimum, a 16px gutter, and
 * cards stretched so every card in a row matches the tallest one. Capped at
 * the console measure so cards don't sprawl on an ultrawide display.
 *
 * The track minimum is `min(300px, 100%)` rather than a bare `300px`: on a
 * ~320px phone the content box is narrower than 300px, and a fixed minimum
 * would size the track past the container and scroll the page sideways.
 *
 * Children opt into wider spans with `PanelCard`'s `span` prop; group labels
 * (`GroupLabel`) span the full row on their own.
 *
 * Renders a `<div>` by default. Pass `as="ul"` when the cards are a genuine
 * list of like things (the device stack) so the count is announced — the
 * caller is then responsible for wrapping each card in an `<li>`.
 */
withDefaults(defineProps<{ as?: 'div' | 'ul' }>(), { as: 'div' })
</script>

<template>
  <component
    :is="as"
    class="m-0 grid max-w-console list-none grid-cols-[repeat(auto-fill,minmax(min(300px,100%),1fr))] items-stretch gap-4 p-0"
  >
    <slot />
  </component>
</template>
