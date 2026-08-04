<script setup lang="ts">
import { computed } from 'vue'

import type { HotspotClient } from '@/api/client'
import EmptyState from '@/components/base/EmptyState.vue'
import MonoValue from '@/components/base/MonoValue.vue'
import SectionHeading from '@/components/base/SectionHeading.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'

/**
 * The hotspot's DHCP leases.
 *
 * Titled "Recent DHCP leases", not "Connected clients", and that wording is
 * load-bearing. A lease is not an association: a client that walked out of
 * range keeps its lease until it expires, and a statically-addressed client
 * never appears at all. Calling this a connection list would state something
 * the data cannot support, so expired leases are shown and marked rather than
 * hidden.
 *
 * Three distinct states, and collapsing any two of them would lie:
 *  - `null`   — this host could not be asked at all.
 *  - `[]`     — it was asked, and nothing has taken a lease.
 *  - entries  — these machines were issued an address.
 */
const props = defineProps<{
  /** `null` means unknown. Never render it as "none connected". */
  clients: HotspotClient[] | null
}>()

const sortedClients = computed(() =>
  props.clients === null
    ? []
    : [...props.clients].sort((left, right) => {
        // Live leases first, then most-recently-expiring, so the machines that
        // are probably actually there sit at the top.
        if (left.expired !== right.expired) return left.expired ? 1 : -1
        return right.lease_expires_at_ms - left.lease_expires_at_ms
      }),
)
</script>

<template>
  <section class="flex flex-col gap-3" aria-labelledby="hotspot-clients-heading">
    <SectionHeading id="hotspot-clients-heading" :level="3">Recent DHCP leases</SectionHeading>

    <p v-if="clients === null" class="m-0 text-[12px] leading-[1.6] text-signal-muted">
      This Sentry cannot report leases — it has no readable lease file. That is not the same as
      nobody being connected.
    </p>

    <EmptyState
      v-else-if="sortedClients.length === 0"
      title="No leases yet"
      detail="Devices appear here shortly after they join the network."
    />

    <ul v-else class="m-0 flex list-none flex-col gap-2 p-0" aria-label="Recent DHCP leases">
      <li
        v-for="client in sortedClients"
        :key="client.mac_address"
        class="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-rack bg-ground-raised px-3 py-2"
      >
        <MonoValue :value="client.ip_address" class="text-[13px] font-semibold text-ink-primary" />
        <span class="text-[12px] text-ink-primary">{{ client.hostname ?? 'Unnamed device' }}</span>
        <MonoValue :value="client.mac_address" class="text-[11px] text-signal-muted" />
        <StatusBadge :tone="client.expired ? 'neutral' : 'ok'">
          {{ client.expired ? 'Lease expired' : 'Lease active' }}
        </StatusBadge>
      </li>
    </ul>

    <p
      v-if="clients !== null && sortedClients.length > 0"
      class="m-0 text-[11px] text-signal-muted"
    >
      A lease shows that a device was given an address, not that it is still in range.
    </p>
  </section>
</template>
