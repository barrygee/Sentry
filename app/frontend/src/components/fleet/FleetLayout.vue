<script setup lang="ts">
/**
 * The devices section: the stack, and nothing above it.
 *
 * The visible "Devices" band label was removed — the cards are the only thing
 * on the page, so a label naming them said nothing an operator did not already
 * see. The heading survives as screen-reader-only text because two things
 * still depend on it: it is the skip link's destination (`App.vue`), and it is
 * this section's accessible name via `aria-labelledby`. Deleting the element
 * would break both, so it is hidden rather than removed.
 *
 * Page padding and the centred measure live in `FleetView`, on the wrapper
 * shared with the notices and conflict banners.
 */
</script>

<template>
  <section aria-labelledby="devices-heading" class="flex flex-col">
    <h2 id="devices-heading" tabindex="-1" class="sr-only outline-none">Devices</h2>
    <slot name="devices" />
  </section>
</template>
