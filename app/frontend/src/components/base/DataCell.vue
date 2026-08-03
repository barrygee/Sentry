<script setup lang="ts">
/**
 * A single labelled readout: caption above, value below, on whatever surface
 * hosts it — no fill, no border.
 *
 * Matches Sentinel's `BaseDataCell` (its POSITION / ORBITAL telemetry cells):
 * a 4px-gap column above a value.
 *
 * The caption is white and bold, and tracked at 0.18em rather than Sentinel's
 * 0.14em for this cell: a card row mixes these readouts with editable fields,
 * and two caption treatments sitting side by side read as an inconsistency
 * rather than as a distinction. Sentinel's own caption is
 * `rgba(255,255,255,.35)`, which is 3.18:1 here and fails AA regardless.
 *
 * `labelTag`/`valueTag` exist so a caller can keep real markup semantics —
 * `DeviceIdentitySummary` renders its pairs inside a `<dl>` and passes
 * `dt`/`dd`, which a hardcoded `<span>` would have quietly thrown away.
 */
withDefaults(
  defineProps<{
    /** The caption, e.g. "Serial number". Rendered uppercase by CSS. */
    label: string
    /** Plain-text value. Ignored when the default slot supplies richer content. */
    value?: string | number | null
    /** Element for the caption — `dt` inside a description list. */
    labelTag?: 'span' | 'dt'
    /** Element for the value — `dd` inside a description list. */
    valueTag?: 'span' | 'dd'
  }>(),
  { value: null, labelTag: 'span', valueTag: 'span' },
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1">
    <component
      :is="labelTag"
      class="font-sans text-[9px] font-bold uppercase tracking-control text-white"
    >
      {{ label }}
    </component>
    <component
      :is="valueTag"
      class="m-0 whitespace-nowrap font-sans text-[12px] font-normal leading-[24px] tracking-data text-white"
    >
      <slot>{{ value }}</slot>
    </component>
  </div>
</template>
