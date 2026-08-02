<script setup lang="ts">
/**
 * The card every panel surface is built from: square corners, a flat panel
 * fill, 22px of padding, and a stack of an optional label/description block
 * above whatever control the caller slots in.
 *
 * Sentinel separates its surfaces with a hairline border rather than a shadow,
 * which reads as nothing on a near-black ground; the same separation here
 * comes from the panel fill sitting one step above the page plus that border.
 *
 * The card title uses Sentinel's condensed station-name treatment (Barlow
 * Condensed, uppercase, lightly tracked) — the closest thing in its dark
 * chrome to "the name of the thing this panel is about".
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
  <component
    :is="as"
    class="flex list-none flex-col items-stretch gap-4 border border-ground-hairline bg-ground-panel p-card"
  >
    <div v-if="label || description || $slots.header" class="flex flex-col gap-1.5">
      <slot name="header">
        <component
          :is="labelLevel === 'none' ? 'span' : `h${labelLevel}`"
          v-if="label"
          class="m-0 font-condensed text-[14px] font-normal uppercase tracking-readout text-ink-primary"
        >
          {{ label }}
        </component>
        <p v-if="description" class="m-0 text-[12px] leading-[1.6] text-signal-muted">
          {{ description }}
        </p>
      </slot>
    </div>
    <slot />
  </component>
</template>
