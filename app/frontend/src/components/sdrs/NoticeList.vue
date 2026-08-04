<script setup lang="ts">
import { computed } from 'vue'

import ConfirmIconAction from '@/components/base/ConfirmIconAction.vue'
import NoticeBox, { type NoticeTone } from '@/components/base/NoticeBox.vue'
import { useSdrsStore } from '@/stores/sdrs'
import type { NoticeLevel } from '@/types/sdrs'

/**
 * The SDR-wide operational notice log (architecture §7.3 SSE `notice`
 * events, plus every failed PATCH/serial-flash attempt) — `stores/sdrs`
 * has always collected these, but until this component nothing rendered
 * them: `crash_loop`, `spawn_failed`, `index_unresolved`, `relay_wedge_exit`
 * and `port_conflict` were silently swallowed, and `dismissNotice` was
 * unreachable. Each notice is independently dismissible and keyboard
 * reachable; `info` notices use `role="status"`, `warn`/`error` use
 * `role="alert"` so they interrupt appropriately without duplicating the
 * app-root live announcer (this list is the persistent record, not the
 * announcement itself).
 */
const sdrsStore = useSdrsStore()

const visibleNotices = computed(() => sdrsStore.notices.filter((notice) => !notice.dismissed))

function roleFor(level: NoticeLevel): 'status' | 'alert' {
  return level === 'info' ? 'status' : 'alert'
}

function toneFor(level: NoticeLevel): NoticeTone {
  switch (level) {
    case 'error':
      return 'danger'
    case 'warn':
      return 'warn'
    default:
      return 'info'
  }
}
</script>

<template>
  <ul
    v-if="visibleNotices.length > 0"
    class="m-0 flex list-none flex-col gap-2 p-0"
    aria-label="Notices"
  >
    <li v-for="notice in visibleNotices" :key="notice.id">
      <NoticeBox :tone="toneFor(notice.level)" :role="roleFor(notice.level)">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <p class="m-0">{{ notice.message }}</p>
          <ConfirmIconAction
            class="self-start"
            :accessible-name="`Dismiss notice: ${notice.message}`"
            confirm-accessible-name="Confirm dismiss notice"
            cancel-accessible-name="Cancel dismissing notice"
            armed-announcement="Confirm dismissing this notice, or cancel."
            cancelled-announcement="Dismissing notice cancelled."
            @confirm="sdrsStore.dismissNotice(notice.id)"
          />
        </div>
      </NoticeBox>
    </li>
  </ul>
</template>
