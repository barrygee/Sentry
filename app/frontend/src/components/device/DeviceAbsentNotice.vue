<script setup lang="ts">
import NoticeBox from '@/components/base/NoticeBox.vue'

/**
 * The inline "this device isn't plugged in" note on a configured device's
 * card. Neutral-toned: an absent ghost is an expected state, not a fault, so
 * it gets the plain raised wash rather than a warning colour.
 */
withDefaults(defineProps<{ lastTopologyPath?: string | null }>(), { lastTopologyPath: null })
</script>

<template>
  <NoticeBox tone="neutral">
    <p class="m-0">
      Device absent<span v-if="lastTopologyPath"> — was in USB port {{ lastTopologyPath }}</span
      >.
    </p>
  </NoticeBox>
</template>
