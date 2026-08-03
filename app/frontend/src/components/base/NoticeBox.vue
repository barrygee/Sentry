<script setup lang="ts">
import { computed } from 'vue'

/**
 * The inset, tinted callout used for every warning, error and inline
 * explanation: a translucent wash of its tone carrying matching text, with no
 * border — the wash alone separates it from the surface behind.
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
  danger: 'bg-signal-danger/[0.08] text-signal-danger',
  warn: 'bg-signal-warn/[0.08] text-signal-warn',
  info: 'bg-signal-info/[0.08] text-signal-info',
  ok: 'bg-signal-ok/[0.08] text-signal-ok',
  neutral: 'bg-ground-raised text-signal-muted',
} as const satisfies Record<NoticeTone, string>

const toneClass = computed(() => TONE_CLASSES[props.tone])
</script>

<template>
  <div
    :role="props.role ?? undefined"
    class="flex flex-col gap-2 rounded-rack px-4 py-3 text-[12.5px] leading-[1.55]"
    :class="toneClass"
  >
    <slot />
  </div>
</template>
