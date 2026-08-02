<script setup lang="ts">
import { computed } from 'vue'

import StatusBadge from '@/components/base/StatusBadge.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import type { DeviceState } from '@/components/base/StatusDot.vue'

/**
 * A device's state, as an unfilled label beside a coloured glyph.
 *
 * The label's own tone stays neutral rather than tracking the state's colour:
 * `StatusDot` already carries that in the glyph, and colouring the word too
 * would say the same thing twice.
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
