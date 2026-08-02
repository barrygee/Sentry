<script setup lang="ts">
/**
 * The device stack: one centred column, cards laid out vertically.
 *
 * This replaced an auto-filling card grid that placed cards side by side at
 * wider viewports. A fleet is a handful of dongles, and reading them as a
 * single ordered list beats packing them into columns. The centred 860px
 * measure they sit in belongs to `FleetView`'s page wrapper, shared with the
 * notices and banners above them.
 *
 * Renders a `<div>` by default. Pass `as="ul"` when the cards are a genuine
 * list of like things, in which case the caller wraps each in an `<li>`.
 */
withDefaults(defineProps<{ as?: 'div' | 'ul' }>(), { as: 'div' })
</script>

<template>
  <component :is="as" class="m-0 flex list-none flex-col gap-4 p-0">
    <slot />
  </component>
</template>
