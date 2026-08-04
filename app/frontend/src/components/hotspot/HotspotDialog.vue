<script setup lang="ts">
import { computed, useId, watch } from 'vue'

import type { HotspotConfigRequest } from '@/api/client'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseDialog from '@/components/base/BaseDialog.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'
import SectionHeading from '@/components/base/SectionHeading.vue'
import HotspotClientList from '@/components/hotspot/HotspotClientList.vue'
import HotspotConfirmCountdown from '@/components/hotspot/HotspotConfirmCountdown.vue'
import HotspotForm from '@/components/hotspot/HotspotForm.vue'
import HotspotSetupHelp from '@/components/hotspot/HotspotSetupHelp.vue'
import HotspotStatusPanel from '@/components/hotspot/HotspotStatusPanel.vue'
import { useHotspotStore } from '@/stores/hotspot'

/**
 * The hotspot settings surface: status, form, confirmation window, leases.
 *
 * Rendered once near the app root and opened from the store, the same shape
 * `SerialFlashDialog` uses — the invoking control (the header gear) is several
 * components away from where the dialog is mounted, so a shared store field is
 * the only sensible source of truth for "is it open".
 *
 * Dismissal is suppressed while a request is in flight **and** while a change is
 * awaiting confirmation. A stray Escape during the confirmation window would
 * read as walking away from a network change that is already live on the
 * hardware, which is exactly when an operator most needs the countdown in front
 * of them.
 */
const hotspotStore = useHotspotStore()

const headingId = useId()

const isBusy = computed(() => hotspotStore.phase === 'submitting')
const state = computed(() => hotspotStore.state)

/**
 * The confirmation deadline, or null when no change is on trial.
 *
 * Narrowed here rather than inline in the template so the countdown receives a
 * plain `number` — the generated type makes the field optional, and a `v-if`
 * on two separate expressions does not narrow it for the binding beside it.
 */
const confirmDeadlineMs = computed(() => {
  const current = state.value
  if (!current?.pending_confirmation) return null
  return current.confirm_deadline_ms ?? null
})

const blockedReason = computed(() => {
  const current = state.value
  if (!current) return null
  if (!current.control_enabled) {
    return 'Hotspot control is switched off on this Sentry. Set SENTRY_HOTSPOT_CONTROL_ENABLED=true in its .env file and restart it.'
  }
  if (!current.auth_token_configured) {
    return 'Set an API access token (SENTRY_AUTH_TOKEN) before starting a hotspot. Without one, anyone who joins the network can reach this API with no credentials.'
  }
  if (!current.available) {
    return 'This Sentry cannot manage a WiFi hotspot: NetworkManager was not reachable. On the Pi, check that NetworkManager is running and that the D-Bus socket is mounted into the container.'
  }
  return null
})

// Refetch whenever the dialog opens so a hotspot changed elsewhere (or rolled
// back while the tab was closed) is never shown stale.
watch(
  () => hotspotStore.dialogOpen,
  (isOpen) => {
    if (isOpen) void hotspotStore.refresh()
  },
)

function close(): void {
  hotspotStore.closeDialog()
}

async function save(config: HotspotConfigRequest): Promise<void> {
  await hotspotStore.save(config)
}

async function confirmHotspot(): Promise<void> {
  await hotspotStore.confirm()
}

async function discardHotspot(): Promise<void> {
  await hotspotStore.disable(true)
}
</script>

<template>
  <BaseDialog
    :open="hotspotStore.dialogOpen"
    :labelled-by="headingId"
    :disable-dismiss="isBusy || hotspotStore.isAwaitingConfirmation"
    @close="close"
  >
    <div class="flex max-h-[80vh] flex-col gap-6 overflow-y-auto">
      <!-- A div, not a header: this is teleported to <body>, and a second
           banner landmark on the page would be wrong. Same reasoning the app's
           other dialogs record. -->
      <div class="flex flex-col gap-2">
        <SectionHeading :id="headingId" :level="2">WiFi hotspot</SectionHeading>
        <p class="m-0 text-[12px] leading-[1.6] text-signal-muted">
          Run a WiFi network from this Sentry so clients can reach the SDRs with no LAN. This is in
          addition to how you connect today — nothing about your existing setup changes.
        </p>
      </div>

      <!-- Both live regions stay mounted for the dialog's whole lifetime and
           only change text. Mounting a live region that already contains its
           message frequently announces nothing at all. -->
      <p role="status" class="sr-only">
        {{ isBusy ? 'Applying hotspot settings.' : '' }}
      </p>
      <p role="alert" class="sr-only">
        {{
          hotspotStore.phase === 'failed' && hotspotStore.errorMessage
            ? hotspotStore.errorMessage
            : ''
        }}
      </p>

      <template v-if="state === null">
        <p class="m-0 text-[12px] text-signal-muted">Loading hotspot settings…</p>
      </template>

      <template v-else>
        <HotspotStatusPanel :state="state" />

        <HotspotConfirmCountdown
          v-if="confirmDeadlineMs !== null"
          :deadline-ms="confirmDeadlineMs"
          :busy="isBusy"
          @confirm="confirmHotspot"
          @discard="discardHotspot"
        />

        <HotspotSetupHelp
          v-if="!state.control_enabled || !state.auth_token_configured"
          :control-enabled="state.control_enabled"
          :auth-token-configured="state.auth_token_configured"
        />
        <NoticeBox v-else-if="blockedReason" tone="warn" role="alert">
          {{ blockedReason }}
        </NoticeBox>

        <NoticeBox
          v-if="state.warnings.includes('advertised_host_overrides_gateway')"
          tone="warn"
          role="status"
        >
          This Sentry publishes a fixed address to Sentinel (SENTRY_ADVERTISED_HOST), which is not
          the hotspot’s address. Clients joining the hotspot should use the address shown above
          instead.
        </NoticeBox>

        <NoticeBox
          v-if="hotspotStore.phase === 'failed' && hotspotStore.errorMessage"
          tone="danger"
          role="status"
        >
          {{ hotspotStore.errorMessage }}
        </NoticeBox>

        <HotspotForm
          v-if="!blockedReason"
          :state="state"
          :interfaces="hotspotStore.interfaces"
          :busy="isBusy"
          @submit="save"
        >
          <template #actions="{ canSubmit }">
            <div class="flex flex-wrap items-center gap-2">
              <BaseButton type="submit" variant="primary" :disabled="!canSubmit">
                {{ isBusy ? 'Saving…' : 'Save hotspot settings' }}
              </BaseButton>
              <BaseButton variant="ghost" :disabled="isBusy" @click="close">Close</BaseButton>
            </div>
          </template>
        </HotspotForm>

        <HotspotClientList v-if="state.configured" :clients="hotspotStore.clients" />
      </template>
    </div>
  </BaseDialog>
</template>
