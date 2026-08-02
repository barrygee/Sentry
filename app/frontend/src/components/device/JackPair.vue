<script setup lang="ts">
import DataCell from '@/components/base/DataCell.vue'
import MonoValue from '@/components/base/MonoValue.vue'

/**
 * The signature "Patch Bay" element (architecture §9.5): the IQ port `P` and
 * control port `P+2` rendered as a pair of readouts.
 *
 * Laid out as Sentinel's telemetry cells — caption above value, no fill behind
 * either — rather than the boxed jacks it once drew. A `<dl>` still, so the
 * port numbers stay programmatically associated with their captions; `DataCell`
 * takes `dt`/`dd` so composing it does not cost that.
 *
 * The captions are neutral rather than accent-coloured: the accent belongs to
 * device state and to controls, and repeating it on every card would spend it
 * on chrome.
 */
withDefaults(
  defineProps<{
    iqPort: number | null
    controlPort: number | null
    compact?: boolean
  }>(),
  { compact: false },
)
</script>

<template>
  <dl class="m-0 flex items-start" :class="compact ? 'gap-6' : 'gap-8'">
    <DataCell label="IQ" label-tag="dt" value-tag="dd">
      <span class="sr-only">IQ port </span><MonoValue :value="iqPort ?? '—'" />
    </DataCell>
    <DataCell label="CTRL" label-tag="dt" value-tag="dd">
      <span class="sr-only">control port </span><MonoValue :value="controlPort ?? '—'" />
    </DataCell>
  </dl>
</template>
