<script setup lang="ts">
withDefaults(defineProps<{ lastTopologyPath?: string | null }>(), { lastTopologyPath: null })
</script>

<template>
  <p
    class="rounded-rack border border-signal-slateMuted/60 bg-ground-raised px-3 py-2 text-xs text-signal-slate"
  >
    Device absent<span v-if="lastTopologyPath"> — was in USB port {{ lastTopologyPath }}</span
    >.
  </p>
</template>
