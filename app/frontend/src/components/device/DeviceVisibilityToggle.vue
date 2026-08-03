<script setup lang="ts">
import { computed } from 'vue'

import type { DeviceStatus } from '@/api/client'
import BaseToggle from '@/components/base/BaseToggle.vue'

/**
 * Whether this device is withheld from Sentinel: switched on keeps it out of
 * `GET /api/v1/sdrs` entirely, switched off publishes it there.
 *
 * This is what lets one Sentry run more dongles than it shares — four
 * configured devices with two of them marked private, and a Sentinel querying
 * the export sees exactly the other two.
 *
 * **On the caption.** The label is the stable state word "Private", not an
 * action ("Make private"), because `role="switch"` already announces on/off:
 * an action label makes a screen reader say "Make private, switch, on", which
 * reads as though the *action* is on. "Private, switch, on" says what is true.
 * The visible caption also stays put while the switch moves, which is what
 * makes the two states distinguishable at a glance down a column of cards.
 */
const props = defineProps<{ device: DeviceStatus }>()

const emit = defineEmits<{ commit: ['public' | 'private'] }>()

const isPrivate = computed(() => props.device.visibility === 'private')

function commitVisibility(nextIsPrivate: boolean): void {
  emit('commit', nextIsPrivate ? 'private' : 'public')
}
</script>

<template>
  <BaseToggle
    :model-value="isPrivate"
    label="Private"
    :accessible-name="`Private — keep ${device.name || device.device_id} out of the Sentinel SDR export`"
    @update:model-value="commitVisibility"
  />
</template>
