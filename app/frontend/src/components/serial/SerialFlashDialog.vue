<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'

import { ApiError, type DeviceStatus } from '@/api/client'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseDialog from '@/components/base/BaseDialog.vue'
import BaseField from '@/components/base/BaseField.vue'
import { useFleetStore } from '@/stores/fleet'
import { isDeviceIdle, type DeviceState } from '@/utils/deviceState'
import { validateSerialClientSide } from '@/utils/serialValidation'

/**
 * The guarded EEPROM serial-flash flow (architecture §7.6, §11) — the most
 * dangerous action Sentry can take, since an interrupted `rtl_eeprom -s`
 * write can corrupt a dongle's USB descriptor. Every step says so plainly:
 * the exact serial is echoed back before commit, an explicit
 * acknowledgement gates the destructive button, the form is disabled
 * unless the device is idle, and progress after the `202 Accepted` is
 * driven entirely by the SSE `notice` stream — there is no polling and no
 * synchronous result.
 *
 * Rendered once, near the app root, and fed by `fleetStore.serialFlashDeviceId`
 * (opened by `SdrDeviceCard`'s `request-serial-flash` emit or
 * `SerialConflictBanner`) rather than owning its own visibility — the
 * invoking control can be several components away from wherever this
 * dialog is mounted.
 */
const props = defineProps<{ device: DeviceStatus | null }>()
const emit = defineEmits<{ close: [] }>()

const fleetStore = useFleetStore()

type FlashPhase = 'form' | 'submitting' | 'awaiting-outcome' | 'succeeded' | 'failed'

const phase = ref<FlashPhase>('form')
const serialDraft = ref('')
const acknowledged = ref(false)
const clientError = ref<string | null>(null)
const outcomeMessage = ref<string | null>(null)
const requiresReplug = ref(false)
let requestStartedAtMs = 0

const headingId = useId()

const isOpen = computed(() => props.device !== null)
const deviceLabel = computed(() => props.device?.name || props.device?.device_id || '')
const isDeviceIdleNow = computed(() =>
  props.device ? isDeviceIdle(props.device.state as DeviceState) : false,
)
const isBusy = computed(() => phase.value === 'submitting' || phase.value === 'awaiting-outcome')
const canSubmit = computed(
  () =>
    isDeviceIdleNow.value &&
    !isBusy.value &&
    acknowledged.value &&
    validateSerialClientSide(serialDraft.value) === null,
)

// Reset all transient state whenever the dialog is retargeted at a new
// device (including being closed, which sets `device` back to null).
watch(
  () => props.device?.device_id ?? null,
  () => {
    phase.value = 'form'
    serialDraft.value = ''
    acknowledged.value = false
    clientError.value = null
    outcomeMessage.value = null
    requiresReplug.value = false
  },
)

// Drive the "awaiting-outcome" phase from live SSE notices: the backend
// holds a per-device lock for the whole operation (architecture §7.6 guard
// 5), so the first notice for this device raised after the request was
// accepted is that operation's outcome.
watch(
  () => fleetStore.notices,
  (notices) => {
    if (phase.value !== 'awaiting-outcome' || !props.device) {
      return
    }
    const targetDeviceId = props.device.device_id
    const outcome = notices.find(
      (notice) => notice.device_id === targetDeviceId && notice.ts >= requestStartedAtMs,
    )
    if (!outcome) {
      return
    }
    outcomeMessage.value = outcome.message
    phase.value = outcome.level === 'info' ? 'succeeded' : 'failed'
  },
)

function validateDraft(): void {
  clientError.value = validateSerialClientSide(serialDraft.value)
}

async function submit(): Promise<void> {
  if (!props.device || !canSubmit.value) {
    return
  }
  clientError.value = null
  phase.value = 'submitting'
  requestStartedAtMs = Date.now()
  try {
    const accepted = await fleetStore.flashSerial(props.device.device_id, serialDraft.value)
    requiresReplug.value = accepted.requires_replug
    phase.value = 'awaiting-outcome'
  } catch (error) {
    outcomeMessage.value = humanizeFlashError(error)
    phase.value = 'failed'
  }
}

function retry(): void {
  phase.value = 'form'
  outcomeMessage.value = null
}

function requestClose(): void {
  emit('close')
}

/** Maps a thrown `ApiError`'s machine code to an operator-facing sentence — never surfaces a raw code. */
function humanizeFlashError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.detail?.code) {
      case 'device_busy':
        return 'This device became busy before the flash could start. Disable it and try again.'
      case 'serial_in_use':
        return 'That serial is already used by another device. Choose a different one.'
      case 'device_unidentified':
        return 'This device could not be resolved to a physical index. Replug it and try again.'
      case 'rtl_eeprom_unavailable':
        return 'The rtl_eeprom tool is unavailable on this Sentry host.'
      case 'flash_failed':
        return 'The write failed partway through. Check the device is still connected.'
      case 'invalid_serial':
        return 'That serial was rejected by the server — use 1-32 letters, numbers, hyphens or underscores.'
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
      <header class="flex flex-col gap-1">
        <h2
          :id="headingId"
          class="font-condensed text-base font-semibold uppercase tracking-legend text-signal-amber"
        >
          Flash a unique serial — {{ deviceLabel }}
        </h2>
        <p class="text-xs text-signal-slate">
          Writes a permanent serial to this dongle's EEPROM via
          <code class="font-mono">rtl_eeprom</code>. This is the most destructive action Sentry can
          take on hardware — an interrupted write can corrupt the device's USB descriptor.
        </p>
      </header>

      <p
        v-if="!isDeviceIdleNow"
        role="alert"
        class="rounded-rack border border-signal-red bg-signal-red/10 px-3 py-2 text-xs text-signal-red"
      >
        This device is currently {{ device.state }}. Disable it and wait until it is idle before
        flashing.
      </p>

      <template v-if="phase === 'form' || phase === 'submitting'">
        <BaseField
          v-model="serialDraft"
          label="New serial"
          hint="1-32 letters, numbers, hyphens or underscores"
          :error="clientError"
          :disabled="!isDeviceIdleNow || isBusy"
          @blur="validateDraft"
        />

        <div
          class="flex flex-col gap-2 rounded-rack border border-signal-amber/60 bg-signal-amber/10 px-3 py-2 text-xs text-signal-amber"
        >
          <p>
            This will stop <strong>{{ deviceLabel }}</strong
            >'s pair (if running), then write
            <strong class="font-mono">{{ serialDraft || '—' }}</strong> to its EEPROM. A physical
            replug is required afterwards before the new serial is visible.
          </p>
          <label class="flex items-start gap-2">
            <input
              v-model="acknowledged"
              type="checkbox"
              class="mt-0.5 h-4 w-4 shrink-0"
              :disabled="!isDeviceIdleNow || isBusy"
            />
            <span>I understand this writes to hardware and cannot be undone.</span>
          </label>
        </div>

        <div class="flex flex-wrap justify-end gap-2">
          <BaseButton variant="ghost" :disabled="isBusy" @click="requestClose">Cancel</BaseButton>
          <BaseButton variant="danger" :disabled="!canSubmit" @click="submit">
            {{ phase === 'submitting' ? 'Starting…' : 'Flash serial' }}
          </BaseButton>
        </div>
      </template>

      <p v-else-if="phase === 'awaiting-outcome'" role="status" class="text-sm text-signal-slate">
        Writing EEPROM — do not unplug {{ deviceLabel }}…
      </p>

      <div v-else-if="phase === 'succeeded'" class="flex flex-col gap-3">
        <p
          role="status"
          class="rounded-rack border border-signal-lime/60 bg-signal-lime/10 px-3 py-2 text-xs text-signal-lime"
        >
          {{ outcomeMessage ?? 'Serial flashed successfully.' }}
          <template v-if="requiresReplug"> Replug the device to see the new serial.</template>
        </p>
        <div class="flex justify-end">
          <BaseButton variant="primary" @click="requestClose">Close</BaseButton>
        </div>
      </div>

      <div v-else-if="phase === 'failed'" class="flex flex-col gap-3">
        <p
          role="alert"
          class="rounded-rack border border-signal-red bg-signal-red/10 px-3 py-2 text-xs text-signal-red"
        >
          {{ outcomeMessage }}
        </p>
        <div class="flex flex-wrap justify-end gap-2">
          <BaseButton variant="ghost" @click="requestClose">Close</BaseButton>
          <BaseButton variant="primary" @click="retry">Try again</BaseButton>
        </div>
      </div>
    </template>
  </BaseDialog>
</template>
