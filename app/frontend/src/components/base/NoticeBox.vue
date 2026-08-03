<script setup lang="ts">
import { computed } from 'vue'

/**
 * The inset, tinted callout used for every warning, error and inline
 * explanation: a light wash of its tone carrying matching text, with no border.
 *
 * Each tone is a SOLID fill carrying white text, not a tint of itself. A wash
 * is a pale ghost of a colour however it is tuned — and these are the loudest
 * things on the page, so they should be the colour rather than a hint of it.
 * White clears 4.5:1 on every tone (danger 5.49, warn 6.82, info 6.16, ok 6.52).
 *
 * `neutral` stays a light fill: it carries "this is just so you know", not an
 * alarm, and a solid grey slab would shout as loudly as an error.
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
  danger: 'bg-signal-danger text-white',
  warn: 'bg-signal-warn text-white',
  info: 'bg-signal-info text-white',
  ok: 'bg-signal-ok text-white',
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
