<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'

import { ApiError, type DeviceStatus } from '@/api/client'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseDialog from '@/components/base/BaseDialog.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'
import SectionHeading from '@/components/base/SectionHeading.vue'
import { useSdrsStore } from '@/stores/sdrs'

/**
 * The confirmation for discarding an absent device's persisted
 * configuration. Reuses `BaseDialog` for its focus-trap/Escape/focus-restore
 * behaviour rather than reimplementing modal semantics. Deleting is
 * recoverable in the sense that replugging the hardware re-detects it, but
 * the name/port/tuning defaults are genuinely gone, so the copy says that
 * plainly instead of a generic "are you sure".
 *
 * Rendered once near the app root and fed by `sdrsStore.forgetDeviceId`
 * (opened from `SdrDeviceCard`'s `request-forget-device` emit), matching the
 * `SerialFlashDialog` pattern — the invoking control lives inside
 * `AbsentDeviceGroup`, several components away from wherever this mounts.
 */
const props = defineProps<{ device: DeviceStatus | null }>()
const emit = defineEmits<{ close: [] }>()

const sdrsStore = useSdrsStore()

type ForgetPhase = 'confirm' | 'deleting' | 'failed'

const phase = ref<ForgetPhase>('confirm')
const errorMessage = ref<string | null>(null)

const headingId = useId()
const consequenceId = `${headingId}-consequence`

const isOpen = computed(() => props.device !== null)
const deviceLabel = computed(() => props.device?.name || props.device?.device_id || '')
const isBusy = computed(() => phase.value === 'deleting')

// Reset transient state whenever the dialog is retargeted (including closed,
// which sets `device` back to null) so a stale error never reappears for a
// different device.
watch(
  () => props.device?.device_id ?? null,
  () => {
    phase.value = 'confirm'
    errorMessage.value = null
  },
)

function requestClose(): void {
  emit('close')
}

async function confirmForget(): Promise<void> {
  if (!props.device || isBusy.value) {
    return
  }
  phase.value = 'deleting'
  errorMessage.value = null
  try {
    await sdrsStore.deleteDevice(props.device.device_id)
    // Success closes via `deleteDevice` itself (`closeForgetDialog`), which
    // sets `device` to null and this component's `watch` resets `phase`.
  } catch (error) {
    errorMessage.value = humanizeForgetError(error)
    phase.value = 'failed'
  }
}

/** Maps a thrown `ApiError`'s machine code to an operator-facing sentence, never a raw code. */
function humanizeForgetError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.detail?.code) {
      case 'device_present':
        return 'This device came back online before it could be forgotten — replugging during a flaky USB re-enumeration is exactly the race this guards against. It is no longer absent, so there is nothing to forget right now.'
      case 'unknown_device':
        return 'This device is already gone.'
      default:
        return error.message
    }
  }
  return 'The request failed before it reached the server. Check the connection and try again.'
}
</script>

<template>
  <BaseDialog
    :open="isOpen"
    :labelled-by="headingId"
    :disable-dismiss="isBusy"
    @close="requestClose"
  >
    <template v-if="device">
      <!-- A `<div>`, not `<header>`: this dialog is teleported to `<body>`,
           outside any sectioning root, so `<header>` here would register as
           a second page-level "banner" landmark alongside `SdrsHeader`'s. -->
      <div class="flex flex-col gap-2">
        <!-- Red dot rather than the identity amber: this dialog's whole
             purpose is a destructive confirmation, and the heading is the
             first thing announced. -->
        <SectionHeading :id="headingId" dot-class="bg-signal-danger">
          Forget {{ deviceLabel }}?
        </SectionHeading>
        <p :id="consequenceId" class="m-0 text-[12.5px] leading-[1.55] text-signal-muted">
          This discards <strong>{{ deviceLabel }}</strong
          >'s saved name, output port and tuning defaults. It's recoverable in that replugging the
          hardware re-detects it as a fresh, unconfigured device — but nothing about how it was set
          up is kept.
        </p>
      </div>

      <NoticeBox v-if="phase === 'failed'" tone="danger" role="alert">
        <p class="m-0">{{ errorMessage }}</p>
      </NoticeBox>

      <div class="flex flex-wrap justify-end gap-2">
        <BaseButton variant="ghost" :disabled="isBusy" @click="requestClose">Cancel</BaseButton>
        <BaseButton
          v-if="phase !== 'failed'"
          variant="danger"
          :disabled="isBusy"
          :aria-describedby="consequenceId"
          @click="confirmForget"
        >
          {{ phase === 'deleting' ? 'Forgetting…' : 'Forget device' }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>
