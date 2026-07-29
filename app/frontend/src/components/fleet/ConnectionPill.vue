<script setup lang="ts">
import { computed } from 'vue'

import type { ConnectionState } from '@/composables/useServerSentEvents'

const props = defineProps<{ connection: ConnectionState }>()

const META: Record<ConnectionState, { label: string; colorClass: string }> = {
  live: { label: 'LIVE', colorClass: 'text-signal-lime' },
  connecting: { label: 'CONNECTING', colorClass: 'text-signal-cyan' },
  reconnecting: { label: 'RECONNECTING', colorClass: 'text-signal-amber' },
  offline: { label: 'OFFLINE', colorClass: 'text-signal-red' },
}

const meta = computed(() => META[props.connection])
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-rack border border-ground-hairline px-2 py-1 font-condensed text-xs uppercase tracking-legend"
    :class="meta.colorClass"
  >
    <span aria-hidden="true" class="text-[10px]">●</span>
    {{ meta.label }}
  </span>
</template>
