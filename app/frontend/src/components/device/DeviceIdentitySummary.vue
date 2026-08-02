<script setup lang="ts">
import MonoValue from '@/components/base/MonoValue.vue'

/**
 * The make/model/serial line every `SdrDeviceCard` heads with — the primary
 * way an operator distinguishes two physical dongles, since the device ID
 * alone (`usb:1-1.2`) or a blank/duplicate name tells them nothing. Fed from
 * `DeviceStatus.usb` when present or `usb_last_known` when absent; the
 * caller resolves which source applies since the two are mutually exclusive.
 *
 * The serial is only shown when the device actually reports one — many
 * dongles report none until flashed, and that absence is itself meaningful
 * (it is why the device is topology-bound rather than serial-keyed).
 */
withDefaults(
  defineProps<{
    manufacturer?: string | null
    product?: string | null
    serial?: string | null
  }>(),
  { manufacturer: null, product: null, serial: null },
)
</script>

<template>
  <p
    v-if="manufacturer || product || serial"
    class="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[12px] leading-[1.6] text-signal-muted"
  >
    <span v-if="manufacturer || product">{{
      [manufacturer, product].filter(Boolean).join(' ')
    }}</span>
    <span v-if="serial" class="flex items-baseline gap-1.5">
      <span class="font-sans text-[9px] uppercase tracking-control">SN</span>
      <MonoValue :value="serial" />
    </span>
  </p>
  <p v-else class="m-0 text-[12px] leading-[1.6] text-signal-muted">Make/model unknown</p>
</template>
