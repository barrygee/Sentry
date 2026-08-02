<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { apiClient } from '@/api/client'
import EmptyState from '@/components/base/EmptyState.vue'
import PanelGrid from '@/components/base/PanelGrid.vue'
import AbsentDeviceGroup from '@/components/fleet/AbsentDeviceGroup.vue'
import FleetHeader from '@/components/fleet/FleetHeader.vue'
import FleetLayout from '@/components/fleet/FleetLayout.vue'
import NoticeList from '@/components/fleet/NoticeList.vue'
import SdrDeviceCard from '@/components/device/SdrDeviceCard.vue'
import ForgetDeviceDialog from '@/components/device/ForgetDeviceDialog.vue'
import SerialConflictBanner from '@/components/serial/SerialConflictBanner.vue'
import SerialFlashDialog from '@/components/serial/SerialFlashDialog.vue'
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

function openForgetDialog(deviceId: string): void {
  fleetStore.openForgetDialog(deviceId)
}

function closeForgetDialog(): void {
  fleetStore.closeForgetDialog()
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
    <FleetHeader :connection="fleetStore.connection" />
    <NoticeList />
    <ul
      v-if="visibleConflictGroups.length"
      class="m-0 flex list-none flex-col gap-2 px-5 pt-[26px] md:px-gutter"
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
      <template #devices>
        <EmptyState
          v-if="!hasDevices"
          title="No devices detected"
          detail="Connect an SDR to a USB port on this Pi."
        />
        <template v-else>
          <EmptyState
            v-if="fleetStore.presentDevices.length === 0"
            title="No devices currently plugged in"
            detail="Every configured device below is absent — see the collapsed group beneath."
          />
          <PanelGrid v-else>
            <SdrDeviceCard
              v-for="device in fleetStore.presentDevices"
              :key="device.device_id"
              :device="device"
              @request-serial-flash="openSerialFlashDialog"
              @request-forget-device="openForgetDialog"
            />
          </PanelGrid>
          <AbsentDeviceGroup
            v-if="fleetStore.absentConfiguredDevices.length > 0"
            :devices="fleetStore.absentConfiguredDevices"
            @request-serial-flash="openSerialFlashDialog"
            @request-forget-device="openForgetDialog"
          />
        </template>
      </template>
    </FleetLayout>
    <SerialFlashDialog
      :device="fleetStore.serialFlashDialogDevice"
      @close="closeSerialFlashDialog"
    />
    <ForgetDeviceDialog :device="fleetStore.forgetDialogDevice" @close="closeForgetDialog" />
  </div>
</template>
