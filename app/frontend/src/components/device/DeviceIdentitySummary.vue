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
    class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-signal-slate"
  >
    <span v-if="manufacturer || product">{{
      [manufacturer, product].filter(Boolean).join(' ')
    }}</span>
    <span v-if="serial" class="flex items-baseline gap-1">
      <span class="font-condensed text-[10px] uppercase tracking-legend text-signal-slate">SN</span>
      <MonoValue :value="serial" />
    </span>
  </p>
  <p v-else class="text-xs text-signal-slate">Make/model unknown</p>
</template>
