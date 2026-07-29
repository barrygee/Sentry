<script setup lang="ts">
import { ref } from 'vue'

import BaseField from '@/components/base/BaseField.vue'

/**
 * The device's operator-facing name (architecture §7.5): 1-64 chars,
 * allow-listed charset, unique across the fleet. Validates on blur, not
 * per keystroke — a partially typed name is not an error.
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(defineProps<{ serverError?: string | null; disabled?: boolean }>(), {
  serverError: null,
  disabled: false,
})

const emit = defineEmits<{ commit: [string] }>()

const NAME_PATTERN = /^[A-Za-z0-9 _.\-()/]+$/
const clientError = ref<string | null>(null)

function validateAndCommit(): void {
  const trimmed = modelValue.value.trim()
  if (trimmed.length === 0 || trimmed.length > 64) {
    clientError.value = 'Name must be 1-64 characters.'
    return
  }
  if (!NAME_PATTERN.test(trimmed)) {
    clientError.value = 'Only letters, numbers, spaces and _ . - ( ) / are allowed.'
    return
  }
  clientError.value = null
  emit('commit', trimmed)
}
</script>

<template>
  <BaseField
    v-model="modelValue"
    label="Name"
    hint="1-64 characters"
    :error="clientError ?? props.serverError"
    :disabled="disabled"
    @blur="validateAndCommit"
  />
</template>
