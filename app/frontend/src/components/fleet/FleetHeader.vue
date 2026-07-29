<script setup lang="ts">
import type { ConnectionState } from '@/composables/useServerSentEvents'

import ConnectionPill from './ConnectionPill.vue'

defineProps<{
  connection: ConnectionState
  streamingCount: number
  deviceCount: number
}>()
</script>

<template>
  <header
    class="flex flex-wrap items-center justify-between gap-3 border-b border-ground-hairline bg-ground-page px-4 py-3 sm:px-6"
  >
    <div class="flex items-baseline gap-3">
      <p class="font-condensed text-lg font-semibold uppercase tracking-legend text-signal-amber">
        Sentry
      </p>
      <p class="hidden font-condensed text-xs uppercase tracking-legend text-signal-slate sm:block">
        SDR Fleet Manager
      </p>
    </div>
    <div class="flex items-center gap-3">
      <p class="font-mono text-xs font-mono-tabular text-signal-slate">
        <span class="text-signal-lime">{{ streamingCount }}</span>
        /
        {{ deviceCount }} streaming
      </p>
      <ConnectionPill :connection="connection" />
    </div>
  </header>
</template>
