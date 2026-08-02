<script setup lang="ts">
import SectionHeading from '@/components/base/SectionHeading.vue'
import type { ConnectionState } from '@/composables/useServerSentEvents'

import ConnectionPill from './ConnectionPill.vue'

/**
 * The console's title bar, in Sentinel's heading style: the wordmark as a 21px
 * uppercase heading preceded by the accent dot, sitting directly on the page
 * ground with a generous top gutter and no rule beneath it — the card grid
 * below provides its own separation, so a border here would just add a line
 * the layout doesn't have.
 *
 * The header used to also carry an "N / M streaming" counter. It was removed:
 * every device card already states its own state, so the counter was a summary
 * of what is visible immediately below it. `ConnectionPill` stays, because it
 * reports something no card can — whether the SSE stream is live, and so
 * whether those states are current or frozen.
 */
defineProps<{
  connection: ConnectionState
}>()
</script>

<template>
  <header
    class="flex flex-wrap items-center justify-between gap-4 bg-ground-page px-5 pb-2 pt-6 md:px-gutter md:pt-[34px]"
  >
    <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <SectionHeading :level="1">Sentry</SectionHeading>
      <p class="font-sans text-[10px] uppercase tracking-group text-signal-muted">
        SDR Fleet Manager
      </p>
    </div>
    <ConnectionPill :connection="connection" />
  </header>
</template>
