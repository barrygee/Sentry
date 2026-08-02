<script setup lang="ts">
import { computed } from 'vue'

/**
 * The small tinted status chip (Sentinel `.tle-status-badge`): 10px uppercase
 * Barlow on a translucent wash of its own tone. The one element in the
 * settings vocabulary that keeps a radius, so it reads as a chip rather than
 * a miniature card.
 *
 * Every tone's text colour is verified >=4.5:1 against Sentry's ground tones
 * (see `tailwind.config.ts`) — the wash sits behind it at ~10% alpha, which
 * lightens the effective background by too little to matter.
 */
export type StatusBadgeTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info'

const props = withDefaults(defineProps<{ tone?: StatusBadgeTone }>(), { tone: 'neutral' })

const TONE_CLASSES = {
  neutral: 'bg-ground-raised text-signal-muted',
  accent: 'bg-signal-accent text-ink-on-accent',
  ok: 'bg-signal-ok/10 text-signal-ok',
  warn: 'bg-signal-warn/10 text-signal-warn',
  danger: 'bg-signal-danger/10 text-signal-danger',
  info: 'bg-signal-info/10 text-signal-info',
} as const satisfies Record<StatusBadgeTone, string>

const toneClass = computed(() => TONE_CLASSES[props.tone])
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-chip px-2 py-[3px] font-condensed text-[10px] font-semibold uppercase tracking-legend"
    :class="toneClass"
  >
    <slot />
  </span>
</template>
