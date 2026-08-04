<script setup lang="ts">
import { computed } from 'vue'

import type { ConfigImportResult } from '@/api/client'
import MonoValue from '@/components/base/MonoValue.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'
import type { StatusBadgeTone } from '@/components/base/StatusBadge.vue'

/**
 * What an import actually did, entry by entry.
 *
 * A partial import is the *expected* outcome, not an error: the destination Pi
 * may not have every dongle plugged in yet, and one whose port is already taken
 * should not stop the rest from landing. A bare "imported" toast would hide
 * exactly the thing an operator needs to know — which of their devices did not
 * come across, and why.
 */
const props = defineProps<{ result: ConfigImportResult }>()

const TONE_BY_OUTCOME = {
  applied: 'ok',
  skipped: 'neutral',
  failed: 'danger',
} as const satisfies Record<'applied' | 'skipped' | 'failed', StatusBadgeTone>

const entries = computed(() => props.result.devices ?? [])

const summaryTone = computed<'ok' | 'warn' | 'danger'>(() => {
  if (props.result.devices_failed > 0) return 'danger'
  if (props.result.devices_skipped > 0) return 'warn'
  return 'ok'
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <NoticeBox :tone="summaryTone" role="status">
      {{ result.devices_applied }} applied · {{ result.devices_skipped }} skipped ·
      {{ result.devices_failed }} failed<template v-if="result.hotspot_applied">
        · hotspot settings written</template
      >.
    </NoticeBox>

    <p v-if="result.hotspot_detail" class="m-0 text-[11px] leading-[1.6] text-signal-muted">
      Hotspot: {{ result.hotspot_detail }}
    </p>

    <ul
      v-if="entries.length"
      class="m-0 flex list-none flex-col gap-2 p-0"
      aria-label="Import results"
    >
      <li
        v-for="entry in entries"
        :key="`${entry.identity_kind}:${entry.identity_key}`"
        class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-rack bg-ground-raised px-3 py-2"
      >
        <StatusBadge :tone="TONE_BY_OUTCOME[entry.outcome]">{{ entry.outcome }}</StatusBadge>
        <MonoValue
          :value="`${entry.identity_kind}:${entry.identity_key}`"
          class="text-[12px] text-ink-primary"
        />
        <span v-if="entry.detail" class="w-full text-[11px] leading-[1.6] text-signal-muted">
          {{ entry.detail }}
        </span>
      </li>
    </ul>
  </div>
</template>
