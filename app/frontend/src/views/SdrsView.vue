<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { apiClient } from '@/api/client'
import EmptyState from '@/components/base/EmptyState.vue'
import PanelStack from '@/components/base/PanelStack.vue'
import AbsentDeviceGroup from '@/components/sdrs/AbsentDeviceGroup.vue'
import NoticeList from '@/components/sdrs/NoticeList.vue'
import SdrDeviceCard from '@/components/device/SdrDeviceCard.vue'
import ForgetDeviceDialog from '@/components/device/ForgetDeviceDialog.vue'
import ConfigDialog from '@/components/config/ConfigDialog.vue'
import HotspotDialog from '@/components/hotspot/HotspotDialog.vue'
import SerialConflictBanner from '@/components/serial/SerialConflictBanner.vue'
import SerialFlashDialog from '@/components/serial/SerialFlashDialog.vue'
import { useSdrsStream } from '@/composables/useSdrsStream'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import { useSdrsStore } from '@/stores/sdrs'

const sdrsStore = useSdrsStore()
const { announcePolite, announceAssertive } = useLiveAnnouncer()
useSdrsStream()

// Locally dismissed conflict banners, keyed by serial — dismissing hides the
// summary banner without touching each affected card's own
// `NeedsIdentificationNotice`, and reappears if the underlying conflict
// changes shape (a new device joins it, etc.) since only the exact serial
// dismissed is suppressed.
const dismissedConflictSerials = ref(new Set<string>())
const visibleConflictGroups = computed(() =>
  sdrsStore.serialConflictGroups.filter(
    (group) => !dismissedConflictSerials.value.has(group.serial),
  ),
)

function dismissConflictGroup(serial: string): void {
  dismissedConflictSerials.value = new Set(dismissedConflictSerials.value).add(serial)
}

function openSerialFlashDialog(deviceId: string): void {
  sdrsStore.openSerialFlashDialog(deviceId)
}

function closeSerialFlashDialog(): void {
  sdrsStore.closeSerialFlashDialog()
}

function closeForgetDialog(): void {
  sdrsStore.closeForgetDialog()
}

onMounted(async () => {
  try {
    const devicesResponse = await apiClient.listDevices()
    sdrsStore.setConstraints(devicesResponse.constraints)
  } catch {
    // The SSE `snapshot` still populates the SDRs even if this convenience
    // fetch fails; port constraints simply stay advisory-only until it does.
  }
})

// Announce plug/unplug and state transitions (architecture §9.4) by
// diffing each snapshot against the previous one's `(present, state)` pair.
const previousDeviceSnapshot = new Map<string, { present: boolean; state: string }>()
watch(
  () => sdrsStore.devices,
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

const hasDevices = computed(() => sdrsStore.devices.length > 0)
</script>

<template>
  <div class="flex min-h-full flex-col">
    <!-- Sentinel's settings body gutters. No section heading above the card:
         this console has one subject, so a title naming it would only repeat
         the card beneath. -->
    <div class="flex w-full max-w-content flex-col gap-6 px-5 pb-16 pt-[34px] md:px-gutter">
      <NoticeList />
      <ul
        v-if="visibleConflictGroups.length"
        class="m-0 flex list-none flex-col gap-2 p-0"
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
      <!-- Each device is its own white box on the canvas — no wrapping card and
           no title above them. The heading stays in the DOM, screen-reader
           only: it is the skip link's destination and this section's accessible
           name, and the boxes below would otherwise be an unlabelled run. -->
      <section aria-labelledby="devices-heading" class="flex flex-col gap-4">
        <h2 id="devices-heading" tabindex="-1" class="sr-only outline-none">SDR devices</h2>
        <EmptyState
          v-if="!hasDevices"
          title="No devices detected"
          detail="Connect an SDR to a USB port on this Pi."
        />
        <template v-else>
          <EmptyState
            v-if="sdrsStore.presentDevices.length === 0"
            title="No devices currently plugged in"
            detail="Every configured device below is absent — see the collapsed group beneath."
          />
          <PanelStack v-else>
            <SdrDeviceCard
              v-for="device in sdrsStore.presentDevices"
              :key="device.device_id"
              :device="device"
              @request-serial-flash="openSerialFlashDialog"
            />
          </PanelStack>
          <AbsentDeviceGroup
            v-if="sdrsStore.absentConfiguredDevices.length > 0"
            :devices="sdrsStore.absentConfiguredDevices"
            @request-serial-flash="openSerialFlashDialog"
          />
        </template>
      </section>
    </div>
    <SerialFlashDialog
      :device="sdrsStore.serialFlashDialogDevice"
      @close="closeSerialFlashDialog"
    />
    <ForgetDeviceDialog :device="sdrsStore.forgetDialogDevice" @close="closeForgetDialog" />
    <!-- Mounted once here, beside the other teleported dialogs, and opened from
         the store by the header's control several components away. -->
    <HotspotDialog />
    <ConfigDialog />
  </div>
</template>
