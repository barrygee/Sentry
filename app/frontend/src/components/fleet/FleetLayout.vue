<script setup lang="ts">
import GroupLabel from '@/components/base/GroupLabel.vue'

/**
 * The devices section: its band label and the stack beneath it.
 *
 * Page padding and the centred measure live in `FleetView`, on the one wrapper
 * that also holds the notices and conflict banners — otherwise those would run
 * full-bleed while the cards sat centred, which read as two different pages.
 *
 * The band label is the skip link's destination, so it is visible rather than
 * screen-reader-only: an operator can see where focus landed.
 */
</script>

<template>
  <section aria-labelledby="devices-heading" class="flex flex-col gap-3">
    <GroupLabel id="devices-heading" :level="2" tabindex="-1" class="outline-none">
      Devices
    </GroupLabel>
    <slot name="devices" />
  </section>
</template>
