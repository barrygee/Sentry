<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'

import { ApiError, type DeviceStatus } from '@/api/client'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseDialog from '@/components/base/BaseDialog.vue'
import BaseField from '@/components/base/BaseField.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'
import SectionHeading from '@/components/base/SectionHeading.vue'
import { useFleetStore } from '@/stores/fleet'
import { isDeviceIdle } from '@/utils/deviceState'
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
const consequenceId = `${headingId}-consequence`

const isOpen = computed(() => props.device !== null)
const deviceLabel = computed(() => props.device?.name || props.device?.device_id || '')
const isDeviceIdleNow = computed(() => (props.device ? isDeviceIdle(props.device.state) : false))
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

// `phase` used to gate four separate `v-else-if` branches, each mounting a
// fresh `role="status"`/`role="alert"` element with its text already
// populated — a screen reader that hasn't yet registered a live region on
// the node it is told changed will frequently announce nothing at all, for
// the single highest-stakes action in the product. These two computeds feed
// a pair of *persistent* regions instead (present for this phase group's
// whole lifetime; only their text content and visibility class change).
const statusMessage = computed(() => {
  if (phase.value === 'awaiting-outcome') {
    return `Writing EEPROM — do not unplug ${deviceLabel.value}…`
  }
  if (phase.value === 'succeeded') {
    const base = outcomeMessage.value ?? 'Serial flashed successfully.'
    return requiresReplug.value ? `${base} Replug the device to see the new serial.` : base
  }
  return ''
})
const statusRegionVisible = computed(
  () => phase.value === 'awaiting-outcome' || phase.value === 'succeeded',
)
// These two regions must remain the *same* DOM nodes across phase changes
// (see the comment above), so they carry `NoticeBox`'s look as class strings
// rather than rendering a `NoticeBox` — swapping the component in and out is
// exactly the remount this design avoids.
const NOTICE_BOX_CLASSES = 'rounded-rack px-4 py-3 text-[12px] leading-[1.6]'
const statusRegionClasses = computed(() =>
  phase.value === 'succeeded'
    ? `${NOTICE_BOX_CLASSES} bg-signal-ok/[0.12] text-signal-ok`
    : 'text-[12px] leading-[1.6] text-signal-muted',
)
const alertMessage = computed(() => (phase.value === 'failed' ? (outcomeMessage.value ?? '') : ''))
const alertRegionClasses = `${NOTICE_BOX_CLASSES} bg-signal-danger/[0.12] text-signal-danger`

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
      <!-- A `<div>`, not `<header>`: this dialog is teleported to `<body>`,
           outside any sectioning root, so `<header>` here would register as
           a second page-level "banner" landmark alongside `FleetHeader`'s. -->
      <div class="flex flex-col gap-2">
        <SectionHeading :id="headingId" dot-class="bg-signal-danger">
          Flash a unique serial — {{ deviceLabel }}
        </SectionHeading>
        <p class="m-0 text-[12px] leading-[1.6] text-signal-muted">
          Writes a permanent serial to this dongle's EEPROM via
          <code class="font-mono">rtl_eeprom</code>. This is the most destructive action Sentry can
          take on hardware — an interrupted write can corrupt the device's USB descriptor.
        </p>
      </div>

      <NoticeBox v-if="!isDeviceIdleNow" tone="danger" role="alert">
        <p class="m-0">
          This device is currently {{ device.state }}. Disable it and wait until it is idle before
          flashing.
        </p>
      </NoticeBox>

      <template v-if="phase === 'form' || phase === 'submitting'">
        <BaseField
          v-model="serialDraft"
          label="New serial"
          hint="1-32 letters, numbers, hyphens or underscores"
          :error="clientError"
          :disabled="!isDeviceIdleNow || isBusy"
          @blur="validateDraft"
        />

        <NoticeBox tone="warn">
          <p :id="consequenceId" class="m-0">
            This will stop <strong>{{ deviceLabel }}</strong
            >'s pair (if running), then write
            <strong class="font-mono">{{ serialDraft || '—' }}</strong> to its EEPROM. A physical
            replug is required afterwards before the new serial is visible.
          </p>
          <label class="flex items-start gap-2.5">
            <input
              v-model="acknowledged"
              type="checkbox"
              class="mt-0.5 h-4 w-4 shrink-0 accent-signal-ok"
              :disabled="!isDeviceIdleNow || isBusy"
              :aria-describedby="consequenceId"
            />
            <span>I understand this writes to hardware and cannot be undone.</span>
          </label>
        </NoticeBox>

        <div class="flex flex-wrap justify-end gap-2">
          <BaseButton variant="ghost" :disabled="isBusy" @click="requestClose">Cancel</BaseButton>
          <BaseButton
            variant="danger"
            :disabled="!canSubmit"
            :aria-describedby="consequenceId"
            @click="submit"
          >
            {{ phase === 'submitting' ? 'Starting…' : 'Flash serial' }}
          </BaseButton>
        </div>
      </template>

      <!-- Persistent live regions, one per phase group, present for the whole
           lifetime of an open dialog rather than freshly mounted per phase —
           only their text content and visibility class change, so a screen
           reader that registered the node before this phase began reliably
           hears the update (architecture §9.4). -->
      <p
        role="status"
        aria-atomic="true"
        :class="statusRegionVisible ? statusRegionClasses : 'sr-only'"
      >
        {{ statusMessage }}
      </p>
      <p
        role="alert"
        aria-atomic="true"
        :class="phase === 'failed' ? alertRegionClasses : 'sr-only'"
      >
        {{ alertMessage }}
      </p>

      <div v-if="phase === 'succeeded'" class="flex justify-end">
        <BaseButton variant="primary" @click="requestClose">Close</BaseButton>
      </div>

      <div v-if="phase === 'failed'" class="flex flex-wrap justify-end gap-2">
        <BaseButton variant="ghost" @click="requestClose">Close</BaseButton>
        <BaseButton variant="primary" @click="retry">Try again</BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>
