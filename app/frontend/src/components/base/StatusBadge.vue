<script setup lang="ts">
import { computed } from 'vue'

/**
 * The small tinted status chip (Sentinel `.tle-status-badge`): 10px uppercase
 * Barlow on a translucent wash of its own tone. The one element in the
 * settings vocabulary that keeps a radius, so it reads as a chip rather than
 * a miniature card.
 *
 * Tinted tone on a 12% wash of itself — this is exactly Sentinel's active
 * segmented option (`rgba(200,255,0,.12)` behind `#c8ff00`). Every tone's text
 * colour is verified >=4.5:1 against Sentry's grounds (see
 * `tailwind.config.ts`); the wash sits behind it at 12% alpha, which lightens
 * the effective background by too little to matter.
 */
export type StatusBadgeTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info'

const props = withDefaults(defineProps<{ tone?: StatusBadgeTone }>(), { tone: 'neutral' })

const TONE_CLASSES = {
  neutral: 'bg-white/[0.08] text-signal-muted',
  accent: 'bg-signal-accent/[0.12] text-signal-accent',
  ok: 'bg-signal-ok/[0.12] text-signal-ok',
  warn: 'bg-signal-warn/[0.12] text-signal-warn',
  danger: 'bg-signal-danger/[0.12] text-signal-danger',
  info: 'bg-signal-info/[0.12] text-signal-info',
} as const satisfies Record<StatusBadgeTone, string>

const toneClass = computed(() => TONE_CLASSES[props.tone])
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-chip px-2 py-[3px] font-sans text-[9px] font-bold uppercase tracking-control"
    :class="toneClass"
  >
    <slot />
  </span>
</template>
