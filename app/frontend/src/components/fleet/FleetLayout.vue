<script setup lang="ts">
import GroupLabel from '@/components/base/GroupLabel.vue'

/**
 * The page shell, laid out on Sentinel's gutters: 44px of page padding at `md`
 * and up, and a generous bottom gutter so the last card never sits flush
 * against the viewport edge.
 *
 * A single column. This was a two-column rack with the USB topology tree in a
 * 320px left rail; the tree was removed, and with it the only reason for the
 * second column — the device grid already reflows from one to three columns on
 * its own, so it takes the full width at every breakpoint.
 *
 * The "Devices" band label uses the muted group-label style rather than a
 * second large heading: in this vocabulary a page carries exactly one 21px
 * title (the wordmark in `FleetHeader`) and everything below it is a band
 * label. It is also the skip link's destination, so it is visible rather than
 * screen-reader-only — an operator can see where focus landed.
 */
</script>

<template>
  <div class="flex flex-1 flex-col px-5 pb-16 pt-[26px] md:px-gutter md:pb-[110px]">
    <section aria-labelledby="devices-heading" class="flex flex-col gap-3">
      <GroupLabel id="devices-heading" :level="2" tabindex="-1" class="outline-none">
        Devices
      </GroupLabel>
      <slot name="devices" />
    </section>
  </div>
</template>
