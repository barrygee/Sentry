<script setup lang="ts">
/**
 * A single labelled readout: caption above, value below, on whatever surface
 * hosts it — no fill, no border.
 *
 * Matches Sentinel's `BaseDataCell` (its POSITION / ORBITAL telemetry cells):
 * a 4px-gap column, a 9px/700/0.14em uppercase caption, and a 14px/600/0.06em
 * value in white. The one deviation is the caption colour — Sentinel's
 * `rgba(255,255,255,.35)` is 3.18:1 on this card and fails AA, so `signal.muted`
 * (.5, 5.33:1) is used, the same substitution already made for its field
 * labels and documented in `tailwind.config.ts`.
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
      class="font-sans text-[9px] font-bold uppercase tracking-caption text-signal-muted"
    >
      {{ label }}
    </component>
    <component
      :is="valueTag"
      class="m-0 whitespace-nowrap font-sans text-[14px] font-semibold leading-[24px] tracking-data text-white"
    >
      <slot>{{ value }}</slot>
    </component>
  </div>
</template>
