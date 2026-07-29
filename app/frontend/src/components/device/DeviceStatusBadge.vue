<script setup lang="ts">
import { computed } from 'vue'

import StatusDot from '@/components/base/StatusDot.vue'
import type { DeviceState } from '@/components/base/StatusDot.vue'

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
  <span
    class="inline-flex items-center gap-1.5 rounded-rack border border-ground-hairline bg-ground-raised px-2 py-1 font-condensed text-xs uppercase tracking-legend"
  >
    <StatusDot :state="state" />
    <span v-if="reasonText" class="text-signal-slate normal-case tracking-normal"
      >· {{ reasonText }}</span
    >
  </span>
</template>
