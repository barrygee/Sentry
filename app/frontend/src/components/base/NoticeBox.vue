<script setup lang="ts">
import { computed } from 'vue'

/**
 * The inset, tinted callout used for every warning, error and inline
 * explanation (Sentinel `.settings-connectivity-warning`): a translucent wash
 * of its tone, a matching 1px border, 12px/16px of padding and the one soft
 * radius the settings vocabulary allows besides the status chip.
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
  danger: 'border-signal-danger/50 bg-signal-danger/10 text-signal-danger',
  warn: 'border-signal-warn/50 bg-signal-warn/10 text-signal-warn',
  info: 'border-signal-info/50 bg-signal-info/10 text-signal-info',
  ok: 'border-signal-ok/50 bg-signal-ok/10 text-signal-ok',
  neutral: 'border-ground-hairline bg-ground-raised text-signal-muted',
} as const satisfies Record<NoticeTone, string>

const toneClass = computed(() => TONE_CLASSES[props.tone])
</script>

<template>
  <div
    :role="props.role ?? undefined"
    class="flex flex-col gap-2 rounded-control border px-4 py-3 text-[12.5px] leading-[1.55]"
    :class="toneClass"
  >
    <slot />
  </div>
</template>
