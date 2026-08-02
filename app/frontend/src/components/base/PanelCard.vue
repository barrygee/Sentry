<script setup lang="ts">
import { computed } from 'vue'

/**
 * The card every settings-style surface is built from (Sentinel
 * `.settings-item`): square corners, a flat panel fill, 22px of padding, and
 * a 12px stack of an optional label/description info block above whatever
 * control the caller slots in.
 *
 * Sentinel separates its white cards from the light canvas with a hairline
 * shadow; on Sentry's near-black ground a shadow reads as nothing, so the
 * same separation comes from the panel fill sitting one step above the page
 * plus a hairline border.
 *
 * `accentBorderClass` adds the 3px left stripe used for a device's state —
 * the one place a card carries semantic colour, and never the sole indicator
 * (the state's glyph and label sit inside the card).
 */
const props = withDefaults(
  defineProps<{
    /** Card title, rendered in the uppercase 13px card-label style. Omit for a card that is all control. */
    label?: string | null
    /** Supporting sentence beneath the label. */
    description?: string | null
    /**
     * Grid columns to occupy. `1` is the default 300px-minimum column; `2`
     * and `3` are Sentinel's `--half`/`--triple` for controls that can't be
     * squeezed into one; `full` is `--wide`.
     */
    span?: 1 | 2 | 3 | 'full'
    /** Opt out of row-height stretching (Sentinel `--natural-height`). */
    naturalHeight?: boolean
    /**
     * Tailwind class for the 3px semantic left stripe. Must be a left-edge-only
     * colour (`border-l-*`) — the card carries an all-sides hairline border, so
     * an unscoped `border-*` colour would repaint every edge.
     */
    accentBorderClass?: string | null
    /** Element to render as — `li` inside a `PanelGrid as="ul"`, `article` for a self-contained record. */
    as?: 'div' | 'li' | 'article' | 'section'
    /** Heading level for `label`. Defaults to a non-heading `<span>`. */
    labelLevel?: 2 | 3 | 4 | 'none'
  }>(),
  {
    label: null,
    description: null,
    span: 1,
    naturalHeight: false,
    accentBorderClass: null,
    as: 'div',
    labelLevel: 'none',
  },
)

// Written out in full rather than interpolated: Tailwind's content scanner
// only sees literal class strings, so `col-span-${n}` would be purged.
const SPAN_CLASSES = {
  1: '',
  2: 'sm:col-span-2',
  3: 'sm:col-span-2 lg:col-span-3',
  full: 'col-span-full',
} as const

const spanClass = computed(() => SPAN_CLASSES[props.span])
</script>

<template>
  <component
    :is="as"
    class="flex list-none flex-col items-stretch gap-3 border border-ground-hairline bg-ground-panel p-card"
    :class="[
      spanClass,
      naturalHeight ? 'self-start' : '',
      accentBorderClass ? `border-l-[3px] ${accentBorderClass}` : '',
    ]"
  >
    <div v-if="label || description || $slots.header" class="flex flex-col gap-1.5">
      <slot name="header">
        <component
          :is="labelLevel === 'none' ? 'span' : `h${labelLevel}`"
          v-if="label"
          class="m-0 font-sans text-[13px] font-medium uppercase tracking-label text-ink-primary"
        >
          {{ label }}
        </component>
        <p v-if="description" class="m-0 text-[12.5px] leading-[1.55] text-signal-muted">
          {{ description }}
        </p>
      </slot>
    </div>
    <slot />
  </component>
</template>
