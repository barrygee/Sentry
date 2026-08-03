<script setup lang="ts">
import { nextTick, ref } from 'vue'

import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'

/**
 * An icon-only action that arms before it fires: a ✕ that, once clicked, is
 * replaced by a ✓ to commit and a ✕ to cancel.
 *
 * This is Sentinel's row-action pattern (`SdrFrequencyManagerTab`'s
 * `.sdr-freq-row-del` family), down to the glyphs, sizes and tones — a bare ✕
 * at 35% white, the confirm tick in accent lime, the cancel ✕ reddening on
 * hover.
 *
 * Focus is moved explicitly at every step, which is the whole reason this is a
 * component rather than a pair of buttons at each call site: each transition
 * *destroys the button the user just activated* (✕ → ✓/✕ → gone), and without
 * intervention focus falls to `<body>`, silently dumping a keyboard user out of
 * the list they were working through. Arming focuses the ✓; cancelling returns
 * focus to the ✕ it came from.
 *
 * Each transition is also announced, since a sighted user sees the glyphs swap
 * but a screen-reader user would otherwise get no signal that a confirmation is
 * now pending.
 */
const props = defineProps<{
  /** Accessible name for the idle ✕, e.g. "Dismiss notice: disk full". */
  accessibleName: string
  /** Accessible name for the ✓ that commits. */
  confirmAccessibleName: string
  /** Accessible name for the ✕ that cancels. */
  cancelAccessibleName: string
  /** Spoken when the action arms, e.g. "Confirm dismissing this notice, or cancel". */
  armedAnnouncement: string
  /** Spoken when the action is cancelled. */
  cancelledAnnouncement: string
}>()

const emit = defineEmits<{ confirm: [] }>()

const { announcePolite } = useLiveAnnouncer()

const isArmed = ref(false)
const armButton = ref<HTMLButtonElement | null>(null)
const confirmButton = ref<HTMLButtonElement | null>(null)

async function arm(): Promise<void> {
  isArmed.value = true
  announcePolite(props.armedAnnouncement)
  await nextTick()
  confirmButton.value?.focus()
}

async function cancel(): Promise<void> {
  isArmed.value = false
  announcePolite(props.cancelledAnnouncement)
  await nextTick()
  armButton.value?.focus()
}

function confirm(): void {
  // No disarm and no focus move: confirming removes the thing this action
  // belongs to, so both this component and its focus target are about to go.
  emit('confirm')
}

const ACTION_CLASSES =
  'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-rack bg-transparent leading-none transition-colors'
</script>

<template>
  <div class="flex shrink-0 items-center gap-1">
    <template v-if="isArmed">
      <button
        ref="confirmButton"
        type="button"
        :class="[ACTION_CLASSES, 'text-signal-accent/85 hover:text-signal-accent']"
        :aria-label="confirmAccessibleName"
        @click="confirm"
      >
        <svg
          width="13"
          height="13"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M2.5 7.5l3 3 6-7" />
        </svg>
      </button>
      <button
        type="button"
        :class="[ACTION_CLASSES, 'text-white/45 hover:text-signal-danger/85']"
        :aria-label="cancelAccessibleName"
        @click="cancel"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
        </svg>
      </button>
    </template>
    <button
      v-else
      ref="armButton"
      type="button"
      :class="[ACTION_CLASSES, 'text-white/35 hover:text-white/85']"
      :aria-label="accessibleName"
      @click="arm"
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 14 14"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
      </svg>
    </button>
  </div>
</template>
