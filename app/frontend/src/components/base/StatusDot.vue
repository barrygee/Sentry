<script setup lang="ts">
import { computed } from 'vue'

import { DEVICE_STATE_META, type DeviceState } from '@/utils/deviceState'

export type { DeviceState }

/**
 * The shared state atom used everywhere a device's state appears (topology
 * lug, device card stripe, badge). Colour alone never carries meaning here:
 * each state also has a distinct glyph/shape, and the text label is either
 * visible or exposed to assistive tech via `visuallyHiddenLabel`
 * (architecture §9.4 — "colour is never the sole indicator").
 */
const props = withDefaults(
  defineProps<{
    state: DeviceState
    /** When true the text label is visually hidden but still in the accessibility tree. */
    visuallyHiddenLabel?: boolean
  }>(),
  { visuallyHiddenLabel: false },
)

const meta = computed(() => DEVICE_STATE_META[props.state])
</script>

<template>
  <span class="inline-flex items-center gap-1.5">
    <span
      aria-hidden="true"
      class="font-mono text-[10px] leading-none"
      :class="meta.textColorClass"
      >{{ meta.glyph }}</span
    >
    <span :class="visuallyHiddenLabel ? 'sr-only' : ''">{{ meta.label }}</span>
  </span>
</template>
