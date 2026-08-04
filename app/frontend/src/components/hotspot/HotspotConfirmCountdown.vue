<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'

import BaseButton from '@/components/base/BaseButton.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'

/**
 * The commit-confirm window: a hotspot that is up on trial and will undo itself
 * unless somebody confirms it from the other side.
 *
 * The countdown is announced at 60, 30 and 10 seconds only, never per second.
 * A live region updated once a second is unusable with a screen reader — it
 * talks over everything else and the operator learns nothing they could not get
 * from three checkpoints. The deadline is also rendered as plain text, so the
 * information does not exist solely in a ticking number.
 *
 * No animated progress bar: there is nothing here that motion conveys and text
 * does not, which makes it the wrong place to spend a `prefers-reduced-motion`
 * exception.
 */
const props = withDefaults(
  defineProps<{
    /** Unix ms by which confirmation must arrive. */
    deadlineMs: number
    busy?: boolean
  }>(),
  { busy: false },
)

const emit = defineEmits<{ confirm: []; discard: [] }>()

const { announcePolite } = useLiveAnnouncer()

const secondsRemaining = ref(remainingSeconds())
const announcedThresholds = new Set<number>()
const ANNOUNCE_AT_SECONDS = [60, 30, 10]

function remainingSeconds(): number {
  return Math.max(0, Math.round((props.deadlineMs - Date.now()) / 1000))
}

const tick = setInterval(() => {
  secondsRemaining.value = remainingSeconds()
  for (const threshold of ANNOUNCE_AT_SECONDS) {
    if (secondsRemaining.value <= threshold && !announcedThresholds.has(threshold)) {
      announcedThresholds.add(threshold)
      announcePolite(`${threshold} seconds left to confirm the hotspot, or it will be rolled back.`)
    }
  }
}, 1000)

onScopeDispose(() => clearInterval(tick))

// A new confirmation window is a new set of checkpoints.
watch(
  () => props.deadlineMs,
  () => {
    announcedThresholds.clear()
    secondsRemaining.value = remainingSeconds()
  },
)

const formattedRemaining = computed(() => {
  const minutes = Math.floor(secondsRemaining.value / 60)
  const seconds = secondsRemaining.value % 60
  return minutes > 0 ? `${minutes}m ${String(seconds).padStart(2, '0')}s` : `${seconds}s`
})
</script>

<template>
  <NoticeBox tone="warn" role="status">
    <div class="flex flex-col gap-3">
      <p class="m-0">
        <strong class="font-semibold">Confirm this hotspot to keep it.</strong>
        It is running now, but Sentry will undo the change and restore the previous connection in
        <span class="font-tabular">{{ formattedRemaining }}</span> unless you confirm — that is what
        stops a hotspot nobody can reach from surviving a reboot.
      </p>
      <p class="m-0 text-[11px]">
        If you have just joined the new network and can still see this page, confirming is safe.
      </p>
      <div class="flex flex-wrap gap-2">
        <BaseButton variant="on-bright" :disabled="props.busy" @click="emit('confirm')">
          Keep this hotspot
        </BaseButton>
        <BaseButton variant="on-bright" :disabled="props.busy" @click="emit('discard')">
          Stop it now
        </BaseButton>
      </div>
    </div>
  </NoticeBox>
</template>
