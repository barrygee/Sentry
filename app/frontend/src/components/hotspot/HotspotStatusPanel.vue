<script setup lang="ts">
import { computed } from 'vue'

import type { HotspotState } from '@/api/client'
import BaseCopyButton from '@/components/base/BaseCopyButton.vue'
import DataCell from '@/components/base/DataCell.vue'
import MonoValue from '@/components/base/MonoValue.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'
import type { StatusBadgeTone } from '@/components/base/StatusBadge.vue'

/**
 * What the hotspot is doing right now, and — the part that actually matters —
 * the address a joined client has to be given.
 *
 * That address is the whole point of the feature: Sentinel has no discovery, so
 * a human reads this number off the screen and types it into Sentinel's SDR form
 * on another machine. It gets the largest treatment on the panel and a copy
 * button, because it is the one value here that leaves the browser.
 */
const props = defineProps<{ state: HotspotState }>()

const statusLabel = computed(() => {
  if (!props.state.available) return 'Unavailable'
  if (!props.state.configured) return 'Not set up'
  if (props.state.active) return props.state.pending_confirmation ? 'On trial' : 'Running'
  return 'Stopped'
})

const statusTone = computed<StatusBadgeTone>(() => {
  if (!props.state.available) return 'danger'
  if (!props.state.configured) return 'neutral'
  if (props.state.active) return props.state.pending_confirmation ? 'warn' : 'ok'
  return 'neutral'
})

const bandLabel = computed(() => (props.state.band === 'a' ? '5 GHz' : '2.4 GHz'))
const securityLabel = computed(() =>
  props.state.security === 'wpa3' ? 'WPA3-Personal' : 'WPA2-Personal',
)
const channelLabel = computed(() =>
  props.state.channel === 0 ? 'Automatic' : String(props.state.channel),
)
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-3">
      <StatusBadge :tone="statusTone">{{ statusLabel }}</StatusBadge>
      <span v-if="state.ssid" class="font-tabular text-[14px] font-semibold text-ink-primary">
        {{ state.ssid }}
      </span>
      <StatusBadge v-if="state.configured && state.hidden" tone="info">Hidden</StatusBadge>
    </div>

    <!-- The address a client dials. Given its own block rather than a cell in
         the grid below, because it is the value someone is copying by hand onto
         another machine, not a detail they are skimming. -->
    <div v-if="state.gateway_address && state.active" class="flex flex-col gap-2">
      <span
        class="select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary"
      >
        Address for clients
      </span>
      <div class="flex flex-wrap items-center gap-3">
        <MonoValue
          :value="state.gateway_address"
          class="text-[18px] font-semibold text-ink-primary"
        />
        <BaseCopyButton
          :value="state.gateway_address"
          accessible-name="Copy the hotspot address for clients"
        />
      </div>
      <p class="m-0 text-[11px] leading-[1.6] text-signal-muted">
        Join this network, then enter this address in Sentinel’s SDR settings with each device’s
        port.
      </p>
    </div>

    <dl v-if="state.configured" class="m-0 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
      <DataCell label="Interface" label-tag="dt" value-tag="dd" :value="state.interface ?? '—'" />
      <DataCell label="Security" label-tag="dt" value-tag="dd" :value="securityLabel" />
      <DataCell label="Band" label-tag="dt" value-tag="dd" :value="bandLabel" />
      <DataCell label="Channel" label-tag="dt" value-tag="dd" :value="channelLabel" />
      <DataCell
        label="Starts on boot"
        label-tag="dt"
        value-tag="dd"
        :value="state.enabled ? 'Yes' : 'No'"
      />
      <DataCell
        label="Password"
        label-tag="dt"
        value-tag="dd"
        :value="state.passphrase_set ? 'Set' : 'Not set'"
      />
    </dl>
  </div>
</template>
