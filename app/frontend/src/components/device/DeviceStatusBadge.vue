<script setup lang="ts">
import { computed } from 'vue'

import StatusBadge from '@/components/base/StatusBadge.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import type { DeviceState } from '@/components/base/StatusDot.vue'

/**
 * A device's state as a Sentinel-style status chip (`.tle-status-badge`) —
 * the tinted-wash chip rather than an outlined pill. The wash stays neutral
 * rather than tracking the state's own colour: the state colour is already
 * carried by `StatusDot`'s glyph inside the chip and by the card's left
 * stripe, and a third coloured surface for the same fact made the card read
 * as three competing alerts.
 */

const props = withDefaults(
  defineProps<{
    state: DeviceState
    reason?: string | null
  }>(),
  { reason: null },
)

const reasonText = computed(() => (props.reason ? humanizeReason(props.reason) : null))

function humanizeReason(reason: string): string {
  return reason.replaceAll('_', ' ')
}
</script>

<template>
  <StatusBadge tone="neutral">
    <StatusDot :state="state" />
    <span v-if="reasonText" class="normal-case tracking-normal text-signal-muted"
      >· {{ reasonText }}</span
    >
  </StatusBadge>
</template>
