<script setup lang="ts">
import DataCell from '@/components/base/DataCell.vue'
import MonoValue from '@/components/base/MonoValue.vue'

/**
 * The make/model/serial block every `SdrDeviceCard` heads with — the primary
 * way an operator distinguishes two physical dongles, since the device ID
 * alone (`usb:1-1.2`) or a blank/duplicate name tells them nothing. Fed from
 * `DeviceStatus.usb` when present or `usb_last_known` when absent; the caller
 * resolves which source applies since the two are mutually exclusive.
 *
 * Both facts are labelled readouts rather than a run of inline text: the
 * make/model previously had no label at all, and the serial's was an
 * unexplained "SN". They now use the same `DataCell` treatment as the ports and
 * tuner values, so a card reads as one set of labelled fields.
 *
 * The serial is only shown when the device actually reports one — many dongles
 * report none until flashed, and that absence is itself meaningful (it is why
 * the device is topology-bound rather than serial-keyed).
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
  <dl v-if="manufacturer || product || serial" class="m-0 flex flex-wrap items-start gap-8">
    <DataCell
      v-if="manufacturer || product"
      label="Model"
      label-tag="dt"
      value-tag="dd"
      :value="[manufacturer, product].filter(Boolean).join(' ')"
    />
    <DataCell v-if="serial" label="Serial number" label-tag="dt" value-tag="dd">
      <MonoValue :value="serial" />
    </DataCell>
  </dl>
  <p v-else class="m-0 text-[12px] leading-[1.6] text-signal-muted">Make/model unknown</p>
</template>
