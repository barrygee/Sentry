<script setup lang="ts">
import NoticeBox from '@/components/base/NoticeBox.vue'

/**
 * The "this will cut this Sentry off the network" warning, and the
 * acknowledgement that unlocks it.
 *
 * On a Pi with one radio, raising an access point on the interface that carries
 * the uplink tears that connection down — including, quite possibly, the one
 * carrying the request being made right now. The server refuses outright until
 * `confirm_uplink_loss` is set, so this is the control that sets it.
 *
 * Deliberately a plain checkbox gate rather than a "proceed anyway" button:
 * copies the guarded pattern `SerialFlashDialog` uses for the EEPROM write, the
 * app's other irreversible-feeling action, so the same shape means the same
 * thing in both places.
 */
const acknowledged = defineModel<boolean>({ required: true })

const props = withDefaults(
  defineProps<{
    /** The interface that will be taken over, e.g. "wlan0". */
    interfaceName: string
    /** The network it is currently joined to, when known. */
    stationSsid?: string | null
    disabled?: boolean
  }>(),
  { stationSsid: null, disabled: false },
)
</script>

<template>
  <NoticeBox tone="danger" role="alert">
    <div class="flex flex-col gap-3">
      <p class="m-0">
        <strong class="font-semibold">{{ interfaceName }} is this Sentry’s own connection</strong>
        <template v-if="stationSsid"> to {{ stationSsid }}</template
        >. Starting the hotspot on it will disconnect that link — including this browser, if you are
        using the same network.
      </p>
      <p class="m-0">
        If it does not come back, Sentry undoes the change by itself after the confirmation window.
        Do the first run over Ethernet where you can.
      </p>
      <!-- Nesting alone associates the label, matching `SerialFlashDialog`'s
           acknowledgement checkbox. Adding a `for`/`id` pair on top of the
           nesting left the control with no accessible name at all. -->
      <label class="flex min-h-[44px] cursor-pointer items-center gap-3">
        <input
          v-model="acknowledged"
          type="checkbox"
          :disabled="props.disabled"
          class="h-4 w-4 shrink-0 accent-signal-danger"
        />
        <span class="text-[12px] leading-[1.6]">
          I understand this will disconnect {{ interfaceName }}
        </span>
      </label>
    </div>
  </NoticeBox>
</template>
