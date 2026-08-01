<script setup lang="ts">
/**
 * Shown for a tier-3 identity device (architecture §5.1): two present
 * dongles collapse to the same identity key, so nothing is persisted or
 * spawned until the operator flashes a unique serial.
 */
defineEmits<{ 'request-serial-flash': [] }>()
</script>

<template>
  <div
    class="flex flex-col gap-2 rounded-rack border border-signal-amber/60 bg-signal-amber/10 px-3 py-2 text-xs text-signal-amber"
  >
    <!-- `role="status"` wraps only the announcement text — the button that
         follows is interactive chrome, not part of what should be read out
         when this notice first appears (architecture §9.4). -->
    <p role="status">
      Needs identification — this dongle's factory serial isn't unique enough to remember it across
      reboots.
    </p>
    <button
      type="button"
      class="min-h-[44px] self-start rounded-rack border border-signal-amber px-3 font-condensed text-xs uppercase tracking-legend text-signal-amber"
      @click="$emit('request-serial-flash')"
    >
      Give this dongle a unique serial
    </button>
  </div>
</template>
