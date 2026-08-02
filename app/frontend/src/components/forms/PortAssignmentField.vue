<script setup lang="ts">
import { computed, nextTick, ref, useId } from 'vue'

import type { PortConstraints } from '@/api/client'
import BaseField from '@/components/base/BaseField.vue'
import JackPair from '@/components/device/JackPair.vue'
import { validatePortClientSide } from '@/utils/portValidation'

/**
 * The IQ output port `P` (architecture §7.5, §8) — `P+2` is implicitly
 * reserved. Validates on blur; a server `409 port_conflict`/`port_reserved_*`
 * renders in the same message slot as the client-side check (architecture
 * §9.4 forms rule).
 *
 * The device card's header already renders the committed jack pair as the
 * device's live identity, so this field only renders its own preview jack
 * pair — clearly labelled "Pending" — while the draft differs from
 * `committedIqPort`. That keeps the two `JackPair` instances from reading as
 * accidental duplication: one is what the device *is*, the other is what
 * you are *about to assign*, and it disappears once they agree.
 */
const modelValue = defineModel<number | null>({ required: true })

const props = withDefaults(
  defineProps<{
    constraints: PortConstraints | null
    serverError?: string | null
    ownReservedPorts?: number[]
    portSuggestion?: number | null
    disabled?: boolean
    /** The device's currently-committed IQ port, or `null` when unconfigured. */
    committedIqPort?: number | null
  }>(),
  {
    serverError: null,
    ownReservedPorts: () => [],
    portSuggestion: null,
    disabled: false,
    committedIqPort: null,
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
const pendingPreviewId = `${useId()}-pending-preview`

const isDraftPending = computed(() => modelValue.value !== props.committedIqPort)

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
  <div class="flex flex-col gap-2">
    <BaseField
      ref="fieldRef"
      v-model="textValue"
      label="Output port (P)"
      type="number"
      input-mode="numeric"
      :hint="portSuggestion ? `Suggested: ${portSuggestion}` : 'The relay listens on P and P+2'"
      :error="clientError ?? props.serverError"
      :disabled="props.disabled"
      :described-by="isDraftPending ? pendingPreviewId : null"
      @blur="validateAndCommit"
    />
    <div v-if="isDraftPending" :id="pendingPreviewId" class="flex items-center gap-2">
      <span class="font-sans text-[10px] uppercase tracking-control text-signal-warn">Pending</span>
      <JackPair
        compact
        :iq-port="modelValue"
        :control-port="modelValue !== null ? modelValue + 2 : null"
      />
    </div>
  </div>
</template>
