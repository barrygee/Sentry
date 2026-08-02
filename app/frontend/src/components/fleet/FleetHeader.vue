<script setup lang="ts">
import SectionHeading from '@/components/base/SectionHeading.vue'
import type { ConnectionState } from '@/composables/useServerSentEvents'

import ConnectionPill from './ConnectionPill.vue'

/**
 * The console's title bar, in Sentinel's settings-heading style: the wordmark
 * as a 21px uppercase heading preceded by the accent dot, sitting directly on
 * the page ground with a generous top gutter and no rule beneath it — the
 * card grid below provides its own separation, so a border here would just
 * add a line the settings layout doesn't have.
 */
defineProps<{
  connection: ConnectionState
  streamingCount: number
  deviceCount: number
}>()
</script>

<template>
  <header
    class="flex flex-wrap items-center justify-between gap-4 bg-ground-page px-5 pb-2 pt-6 md:px-gutter md:pt-[34px]"
  >
    <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <SectionHeading :level="1">Sentry</SectionHeading>
      <p
        class="font-condensed text-[10px] font-semibold uppercase tracking-group text-signal-muted"
      >
        SDR Fleet Manager
      </p>
    </div>
    <div class="flex items-center gap-3">
      <p
        class="font-condensed text-[10px] font-semibold uppercase tracking-control text-signal-muted"
      >
        <span class="font-mono font-mono-tabular text-signal-ok">{{ streamingCount }}</span>
        <span aria-hidden="true" class="px-1">/</span>
        <span class="font-mono font-mono-tabular">{{ deviceCount }}</span>
        <span class="pl-2">streaming</span>
      </p>
      <ConnectionPill :connection="connection" />
    </div>
  </header>
</template>
