<script setup lang="ts">
import { nextTick, ref } from 'vue'

import BaseField from '@/components/base/BaseField.vue'

/**
 * The device's operator-facing name (architecture §7.5): 1-64 chars,
 * allow-listed charset, unique across the SDRs. Validates on blur, not
 * per keystroke — a partially typed name is not an error. On a validation
 * failure, focus is returned to the field rather than left wherever the
 * operator tabbed to, so a screen-reader user hears which field the error
 * belongs to.
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(defineProps<{ serverError?: string | null; disabled?: boolean }>(), {
  serverError: null,
  disabled: false,
})

const emit = defineEmits<{ commit: [string] }>()

const NAME_PATTERN = /^[A-Za-z0-9 _.\-()/]+$/
const clientError = ref<string | null>(null)
const fieldRef = ref<InstanceType<typeof BaseField> | null>(null)

function validateAndCommit(): void {
  const trimmed = modelValue.value.trim()
  if (trimmed.length === 0 || trimmed.length > 64) {
    clientError.value = 'Name must be 1-64 characters.'
    void nextTick(() => fieldRef.value?.focus())
    return
  }
  if (!NAME_PATTERN.test(trimmed)) {
    clientError.value = 'Only letters, numbers, spaces and _ . - ( ) / are allowed.'
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
    label="Name"
    :error="clientError ?? props.serverError"
    :disabled="props.disabled"
    @blur="validateAndCommit"
  />
</template>
