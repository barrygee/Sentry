<script setup lang="ts">
import { computed } from 'vue'

import { useFleetStore } from '@/stores/fleet'
import type { NoticeLevel } from '@/types/fleet'

/**
 * The fleet-wide operational notice log (architecture §7.3 SSE `notice`
 * events, plus every failed PATCH/serial-flash attempt) — `stores/fleet`
 * has always collected these, but until this component nothing rendered
 * them: `crash_loop`, `spawn_failed`, `index_unresolved`, `relay_wedge_exit`
 * and `port_conflict` were silently swallowed, and `dismissNotice` was
 * unreachable. Each notice is independently dismissible and keyboard
 * reachable; `info` notices use `role="status"`, `warn`/`error` use
 * `role="alert"` so they interrupt appropriately without duplicating the
 * app-root live announcer (this list is the persistent record, not the
 * announcement itself).
 */
const fleetStore = useFleetStore()

const visibleNotices = computed(() => fleetStore.notices.filter((notice) => !notice.dismissed))

function roleFor(level: NoticeLevel): 'status' | 'alert' {
  return level === 'info' ? 'status' : 'alert'
}

function classesFor(level: NoticeLevel): string {
  switch (level) {
    case 'error':
      return 'border-signal-red bg-signal-red/10 text-signal-red'
    case 'warn':
      return 'border-signal-amber bg-signal-amber/10 text-signal-amber'
    default:
      return 'border-signal-cyan bg-signal-cyan/10 text-signal-cyan'
  }
}
</script>

<template>
  <ul
    v-if="visibleNotices.length > 0"
    class="flex flex-col gap-2 px-4 pt-4 sm:px-6"
    aria-label="Notices"
  >
    <li v-for="notice in visibleNotices" :key="notice.id">
      <div
        :role="roleFor(notice.level)"
        class="flex flex-col gap-2 rounded-rack border px-3 py-2 text-xs sm:flex-row sm:items-start sm:justify-between sm:gap-3"
        :class="classesFor(notice.level)"
      >
        <p>{{ notice.message }}</p>
        <button
          type="button"
          class="min-h-[44px] shrink-0 rounded-rack border px-2 font-condensed text-xs uppercase tracking-legend"
          :class="classesFor(notice.level)"
          @click="fleetStore.dismissNotice(notice.id)"
        >
          Dismiss
          <span class="sr-only">notice: {{ notice.message }}</span>
        </button>
      </div>
    </li>
  </ul>
</template>
