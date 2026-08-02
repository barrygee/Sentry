<script setup lang="ts">
import { computed } from 'vue'

import type { ConnectionState } from '@/composables/useServerSentEvents'

import StatusBadge, { type StatusBadgeTone } from '@/components/base/StatusBadge.vue'

/**
 * The SSE stream's health, as a Sentinel-style status chip
 * (`.tle-status-badge`): a tinted wash rather than an outline. The leading
 * glyph differs per state as well as the colour, so the state is never
 * carried by hue alone.
 */
const props = defineProps<{ connection: ConnectionState }>()

const META: Record<ConnectionState, { label: string; tone: StatusBadgeTone; glyph: string }> = {
  live: { label: 'LIVE', tone: 'ok', glyph: '●' },
  connecting: { label: 'CONNECTING', tone: 'info', glyph: '◐' },
  reconnecting: { label: 'RECONNECTING', tone: 'warn', glyph: '◑' },
  offline: { label: 'OFFLINE', tone: 'danger', glyph: '✕' },
}

const meta = computed(() => META[props.connection])
</script>

<template>
  <StatusBadge :tone="meta.tone">
    <span aria-hidden="true" class="text-[10px] leading-none">{{ meta.glyph }}</span>
    {{ meta.label }}
  </StatusBadge>
</template>
