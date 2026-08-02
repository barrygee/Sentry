<script setup lang="ts">
import { computed, nextTick, ref, useId } from 'vue'

import type { PortConstraints } from '@/api/client'
import BaseField from '@/components/base/BaseField.vue'
import DataCell from '@/components/base/DataCell.vue'
import { validatePortClientSide } from '@/utils/portValidation'

/**
 * The IQ output port `P` (architecture §7.5, §8) — `P+2` is implicitly
 * reserved. Validates on blur; a server `409 port_conflict`/`port_reserved_*`
 * renders in the same message slot as the client-side check (architecture
 * §9.4 forms rule).
 *
 * The relay's two ports are shown beside the input as a readout rather than
 * described in hint text underneath it: "the relay listens on P and P+2" made
 * the operator do the arithmetic, where `1250 / 1252` simply states it. It
 * tracks the *draft* value, so it updates as the field is typed into and
 * doubles as the preview of what is about to be assigned — which is why the
 * separate "Pending" jack pair this component used to render is gone.
 */
const modelValue = defineModel<number | null>({ required: true })

const props = withDefaults(
  defineProps<{
    constraints: PortConstraints | null
    serverError?: string | null
    ownReservedPorts?: number[]
    disabled?: boolean
  }>(),
  {
    serverError: null,
    ownReservedPorts: () => [],
    disabled: false,
  },
)

const emit = defineEmits<{ commit: [number] }>()

const textValue = computed<string>({
  get: () => (modelValue.value === null ? '' : String(modelValue.value)),
  set: (nextText) => {
    const parsed = Number.parseInt(nextText, 10)
    modelValue.value = Number.isNaN(parsed) ? null : parsed
  },
})

const clientError = ref<string | null>(null)
const fieldRef = ref<InstanceType<typeof BaseField> | null>(null)
const relayPortsId = `${useId()}-relay-ports`

/** `P / P+2`, from the draft so it tracks what is being typed, or an em dash while empty. */
const relayPortsSummary = computed(() =>
  modelValue.value === null ? '—' : `${modelValue.value} / ${modelValue.value + 2}`,
)

function validateAndCommit(): void {
  if (modelValue.value === null) {
    clientError.value = 'Port is required.'
    void nextTick(() => fieldRef.value?.focus())
    return
  }
  if (props.constraints) {
    const validationError = validatePortClientSide(
      modelValue.value,
      props.constraints,
      props.ownReservedPorts,
    )
    if (validationError) {
      clientError.value = validationError
      void nextTick(() => fieldRef.value?.focus())
      return
    }
  }
  clientError.value = null
  emit('commit', modelValue.value)
}
</script>

<template>
  <!-- `w-full` so the readout sits beside the input rather than being
       squeezed onto its own row: the parent stacks its fields with
       `items-start`, which otherwise shrink-wraps this row to the input.

       The input is 76px — the measured width of its own "OUTPUT PORT" caption —
       so the field is no wider than the thing naming it. With the 12px side
       padding that leaves 52px of content, which still fits a five-digit port
       (the range runs to 65535), not just the four-digit ones in normal use. -->
  <div class="flex w-full flex-wrap items-start gap-8">
    <BaseField
      ref="fieldRef"
      v-model="textValue"
      label="Output port"
      type="number"
      input-mode="numeric"
      :error="clientError ?? props.serverError"
      :disabled="props.disabled"
      :described-by="relayPortsId"
      class="w-[76px]"
      @blur="validateAndCommit"
    />
    <DataCell :id="relayPortsId" label="Relay listens on" :value="relayPortsSummary" />
  </div>
</template>
