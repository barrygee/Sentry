<script setup lang="ts">
import { computed } from 'vue'

/**
 * The inset, tinted callout used for every warning, error and inline
 * explanation: a light wash of its tone carrying matching text, with no border.
 *
 * The wash is deliberately faint (5%) and the text a step heavier than body
 * copy. On a light ground a tint always mutes the text sitting on it, and a
 * red vivid enough to look bright is too light to clear 4.5:1 at this size —
 * so the strength has to come from weight and a near-clear background rather
 * than from a brighter hue. At 12% the tone was visibly eating its own text.
 *
 * The caller supplies `role` explicitly rather than this component inferring
 * it from `tone` — whether a message should interrupt a screen-reader user
 * depends on when it appears, not on what colour it is. A banner already on
 * the page at load wants `status` (or nothing at all); one that appears in
 * response to an action wants `alert`.
 */
export type NoticeTone = 'danger' | 'warn' | 'info' | 'ok' | 'neutral'

const props = withDefaults(
  defineProps<{
    tone?: NoticeTone
    /** ARIA live semantics. Omit entirely for a notice that is not an announcement. */
    role?: 'status' | 'alert' | null
  }>(),
  { tone: 'info', role: null },
)

const TONE_CLASSES = {
  danger: 'bg-signal-danger/[0.05] text-signal-danger',
  warn: 'bg-signal-warn/[0.05] text-signal-warn',
  info: 'bg-signal-info/[0.05] text-signal-info',
  ok: 'bg-signal-ok/[0.05] text-signal-ok',
  neutral: 'bg-ground-raised text-signal-muted',
} as const satisfies Record<NoticeTone, string>

const toneClass = computed(() => TONE_CLASSES[props.tone])
</script>

<template>
  <div
    :role="props.role ?? undefined"
    class="flex flex-col gap-2 rounded-rack px-4 py-3 text-[12.5px] font-medium leading-[1.55]"
    :class="toneClass"
  >
    <slot />
  </div>
</template>
