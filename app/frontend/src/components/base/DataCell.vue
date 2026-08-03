<script setup lang="ts">
/**
 * A single labelled readout: caption above, value below, on whatever surface
 * hosts it — no fill, no border.
 *
 * Matches Sentinel's `BaseDataCell` (its POSITION / ORBITAL telemetry cells):
 * a 4px-gap column above a value.
 *
 * The caption is 11px/600 at 0.1em — Sentinel's `.settings-item-label`
 * treatment, pulled down from its 13px because a device box stacks far more
 * captions than a settings card does, and at full size they competed with the
 * values they label — and the value takes its `.settings-item-desc` size of
 * 12.5px. Both are a marked step up from the
 * 10px legend this used to use.
 *
 * The value keeps `ink.primary` rather than `.settings-item-desc`'s muted
 * grey: there that step carries explanatory prose beneath a title, whereas
 * here it carries the device's actual data, which should not be the dimmest
 * thing in the box.
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
  <div class="flex min-w-0 flex-col gap-1.5">
    <component
      :is="labelTag"
      class="font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary"
    >
      {{ label }}
    </component>
    <component
      :is="valueTag"
      class="m-0 whitespace-nowrap font-sans text-[12.5px] font-normal leading-[24px] tracking-readout text-ink-primary"
    >
      <slot>{{ value }}</slot>
    </component>
  </div>
</template>
