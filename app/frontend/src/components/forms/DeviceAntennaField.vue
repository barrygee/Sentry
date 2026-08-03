<script setup lang="ts">
import { nextTick, ref } from 'vue'

import BaseField from '@/components/base/BaseField.vue'

/**
 * The antenna this device is fed by, as free text — "Discone, loft",
 * "1090 collinear on the chimney". Purely local documentation: it is never
 * published in `GET /api/v1/sdrs`, so it can name a location as loosely or
 * as precisely as the operator likes.
 *
 * Optional, so an empty value is valid and commits as `""` (which clears any
 * previous entry) rather than being rejected. Validates on blur, matching
 * `DeviceNameField` — a half-typed antenna is not an error — and returns
 * focus to the field when the one rule it does have (120 characters) fails.
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(defineProps<{ serverError?: string | null; disabled?: boolean }>(), {
  serverError: null,
  disabled: false,
})

const emit = defineEmits<{ commit: [string] }>()

/** Mirrors `DevicePatch.antenna`'s `max_length`; the server re-validates regardless. */
const MAX_ANTENNA_LENGTH = 120

const clientError = ref<string | null>(null)
const fieldRef = ref<InstanceType<typeof BaseField> | null>(null)

function validateAndCommit(): void {
  const trimmed = modelValue.value.trim()
  if (trimmed.length > MAX_ANTENNA_LENGTH) {
    clientError.value = `Antenna must be ${MAX_ANTENNA_LENGTH} characters or fewer.`
    void nextTick(() => fieldRef.value?.focus())
    return
  }
  clientError.value = null
  emit('commit', trimmed)
}
</script>

<template>
  <BaseField
    ref="fieldRef"
    v-model="modelValue"
    label="Antenna"
    :error="clientError ?? props.serverError"
    :disabled="props.disabled"
    @blur="validateAndCommit"
  />
</template>
