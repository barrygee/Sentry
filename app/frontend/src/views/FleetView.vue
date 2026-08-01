<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { apiClient } from '@/api/client'
import EmptyState from '@/components/base/EmptyState.vue'
import FleetHeader from '@/components/fleet/FleetHeader.vue'
import FleetLayout from '@/components/fleet/FleetLayout.vue'
import NoticeList from '@/components/fleet/NoticeList.vue'
import SdrDeviceCard from '@/components/device/SdrDeviceCard.vue'
import SerialConflictBanner from '@/components/serial/SerialConflictBanner.vue'
import SerialFlashDialog from '@/components/serial/SerialFlashDialog.vue'
import UsbTopologyTree from '@/components/topology/UsbTopologyTree.vue'
import { useFleetStream } from '@/composables/useFleetStream'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import { useFleetStore } from '@/stores/fleet'

const fleetStore = useFleetStore()
const { announcePolite, announceAssertive } = useLiveAnnouncer()
useFleetStream()

const portSuggestion = ref<number | null>(null)

// Locally dismissed conflict banners, keyed by serial — dismissing hides the
// summary banner without touching each affected card's own
// `NeedsIdentificationNotice`, and reappears if the underlying conflict
// changes shape (a new device joins it, etc.) since only the exact serial
// dismissed is suppressed.
const dismissedConflictSerials = ref(new Set<string>())
const visibleConflictGroups = computed(() =>
  fleetStore.serialConflictGroups.filter(
    (group) => !dismissedConflictSerials.value.has(group.serial),
  ),
)

function dismissConflictGroup(serial: string): void {
  dismissedConflictSerials.value = new Set(dismissedConflictSerials.value).add(serial)
}

function openSerialFlashDialog(deviceId: string): void {
  fleetStore.openSerialFlashDialog(deviceId)
}

function closeSerialFlashDialog(): void {
  fleetStore.closeSerialFlashDialog()
}

onMounted(async () => {
  try {
    const devicesResponse = await apiClient.listDevices()
    fleetStore.setConstraints(devicesResponse.constraints)
    portSuggestion.value = devicesResponse.port_suggestion
  } catch {
    // The SSE `snapshot` still populates the fleet even if this convenience
    // fetch fails; port constraints simply stay advisory-only until it does.
  }
})

function focusDeviceCard(deviceId: string): void {
  void nextTick(() => {
    document.getElementById(`device-card-${deviceId}`)?.focus()
  })
}

// `UsbTopologyTree` resolves the exact sentence itself (it's the only place
// that knows the destination node's label, or that focus went to the
// empty-state panel instead of a tree node) — announced every time,
// matching that a real focus move always happened, rather than only when
// the tree emptied.
function announceFocusRecovered(message: string): void {
  announcePolite(message)
}

// Announce plug/unplug and state transitions (architecture §9.4) by
// diffing each snapshot against the previous one's `(present, state)` pair.
const previousDeviceSnapshot = new Map<string, { present: boolean; state: string }>()
watch(
  () => fleetStore.devices,
  (currentDevices) => {
    for (const device of currentDevices) {
      const previous = previousDeviceSnapshot.get(device.device_id)
      const label = device.name || device.device_id
      if (!previous) {
        if (device.present) {
          announcePolite(`${label} connected, now ${device.state}.`)
        }
      } else if (previous.state !== device.state || previous.present !== device.present) {
        if (device.state === 'error') {
          announceAssertive(
            `${label} error${device.state_reason ? `: ${device.state_reason}` : ''}.`,
          )
        } else if (!device.present && previous.present) {
          announcePolite(`${label} disconnected.`)
        } else {
          announcePolite(`${label} now ${device.state}.`)
        }
      }
      previousDeviceSnapshot.set(device.device_id, { present: device.present, state: device.state })
    }
    for (const knownId of previousDeviceSnapshot.keys()) {
      if (!currentDevices.some((device) => device.device_id === knownId)) {
        previousDeviceSnapshot.delete(knownId)
      }
    }
  },
  { deep: false },
)

const hasDevices = computed(() => fleetStore.devices.length > 0)
</script>

<template>
  <div class="flex min-h-full flex-col">
    <FleetHeader
      :connection="fleetStore.connection"
      :streaming-count="fleetStore.streamingCount"
      :device-count="fleetStore.devices.length"
    />
    <NoticeList />
    <ul
      v-if="visibleConflictGroups.length"
      class="flex flex-col gap-2 px-4 pt-4 sm:px-6"
      aria-label="Serial conflicts"
    >
      <li v-for="group in visibleConflictGroups" :key="group.serial">
        <SerialConflictBanner
          :serial="group.serial"
          :conflicting-devices="group.devices"
          @dismiss="dismissConflictGroup(group.serial)"
          @request-serial-flash="openSerialFlashDialog"
        />
      </li>
    </ul>
    <FleetLayout>
      <template #topology>
        <UsbTopologyTree
          :roots="fleetStore.topologyTree.roots"
          @activate="focusDeviceCard"
          @focus-recovered="announceFocusRecovered"
        />
      </template>
      <template #devices>
        <EmptyState
          v-if="!hasDevices"
          title="No devices detected"
          detail="Connect an SDR to a USB port on this Pi."
        />
        <div v-else class="flex flex-col rounded-rack border border-ground-hairline">
          <SdrDeviceCard
            v-for="device in fleetStore.devices"
            :key="device.device_id"
            :device="device"
            @request-serial-flash="openSerialFlashDialog"
          />
        </div>
      </template>
    </FleetLayout>
    <SerialFlashDialog
      :device="fleetStore.serialFlashDialogDevice"
      @close="closeSerialFlashDialog"
    />
  </div>
</template>
