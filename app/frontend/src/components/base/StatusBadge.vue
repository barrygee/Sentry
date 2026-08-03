<script setup lang="ts">
import { computed } from 'vue'

/**
 * A short uppercase status label: 9px Barlow 700 at 0.18em, coloured by tone.
 *
 * Unfilled. It was a tinted chip — a 12% wash of its own tone, matching
 * Sentinel's active segmented option — but a fill behind the device state read
 * as a third coloured surface on a card that already carries the state as a
 * glyph. It is now the label alone, as the rest of the card is.
 *
 * `neutral` is white rather than grey: the device state is the only 9px
 * uppercase label on a card that is not a field title, and left muted it read
 * as an oversight beside them rather than as a different kind of thing. The
 * state's own colour is carried by `StatusDot`'s glyph, so nothing is lost.
 *
 * Every tone's text colour is verified >=4.5:1 against Sentry's grounds (see
 * `tailwind.config.ts`), which the fill's removal only improves.
 */
export type StatusBadgeTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info'

const props = withDefaults(defineProps<{ tone?: StatusBadgeTone }>(), { tone: 'neutral' })

const TONE_CLASSES = {
  neutral: 'text-ink-primary',
  accent: 'text-signal-accent',
  ok: 'text-signal-ok',
  warn: 'text-signal-warn',
  danger: 'text-signal-danger',
  info: 'text-signal-info',
} as const satisfies Record<StatusBadgeTone, string>

const toneClass = computed(() => TONE_CLASSES[props.tone])
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 font-sans text-[9px] font-bold uppercase tracking-control"
    :class="toneClass"
  >
    <slot />
  </span>
</template>
