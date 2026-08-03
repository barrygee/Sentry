<script setup lang="ts">
/**
 * Shown for a tier-3 identity device (architecture §5.1): two present
 * dongles collapse to the same identity key, so nothing is persisted or
 * spawned until the operator flashes a unique serial.
 */
import BaseButton from '@/components/base/BaseButton.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'

defineEmits<{ 'request-serial-flash': [] }>()
</script>

<template>
  <NoticeBox tone="warn">
    <!-- `role="status"` wraps only the announcement text — the button that
         follows is interactive chrome, not part of what should be read out
         when this notice first appears (architecture §9.4). -->
    <p role="status" class="m-0">
      Needs identification — this dongle's factory serial isn't unique enough to remember it across
      reboots.
    </p>
    <BaseButton variant="on-bright" class="self-start" @click="$emit('request-serial-flash')">
      Give this dongle a unique serial
    </BaseButton>
  </NoticeBox>
</template>
