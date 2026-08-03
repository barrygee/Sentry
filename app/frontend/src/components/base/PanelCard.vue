<script setup lang="ts">
/**
 * The card every panel surface is built from: square corners, a flat panel
 * fill, 22px of padding, and a stack of an optional label/description block
 * above whatever control the caller slots in.
 *
 * Borderless: the card is separated from the page by its fill alone, sitting
 * one step above the black ground. Sentinel's own panels work the same way —
 * flat fills, no outlines.
 *
 * The card title is Sentinel's settings-card treatment: 15px Barlow 600,
 * uppercase, lightly tracked, above a plain description line.
 *
 * Earlier versions carried grid-span props and a 3px semantic left stripe.
 * Both are gone: the stack is a single column so spans mean nothing, and the
 * stripe was removed at the owner's request. Device state is still carried by
 * `DeviceStatusBadge`, which pairs a coloured glyph with a text label, so no
 * information was lost with it.
 */
withDefaults(
  defineProps<{
    /** Card title. Omit for a card that is all control. */
    label?: string | null
    /** Supporting sentence beneath the label. */
    description?: string | null
    /** Element to render as — `li` inside a `PanelStack as="ul"`, `article` for a self-contained record. */
    as?: 'div' | 'li' | 'article' | 'section'
    /** Heading level for `label`. Defaults to a non-heading `<span>`. */
    labelLevel?: 2 | 3 | 4 | 'none'
  }>(),
  {
    label: null,
    description: null,
    as: 'div',
    labelLevel: 'none',
  },
)
</script>

<template>
  <component :is="as" class="flex list-none flex-col items-stretch gap-6 bg-ground-panel p-card">
    <div v-if="label || description || $slots.header" class="flex flex-col gap-1.5">
      <slot name="header">
        <component
          :is="labelLevel === 'none' ? 'span' : `h${labelLevel}`"
          v-if="label"
          class="m-0 font-sans text-[15px] font-semibold uppercase tracking-label text-ink-primary"
        >
          {{ label }}
        </component>
        <p v-if="description" class="m-0 text-[13px] leading-[1.55] text-signal-muted">
          {{ description }}
        </p>
      </slot>
    </div>
    <slot />
  </component>
</template>
