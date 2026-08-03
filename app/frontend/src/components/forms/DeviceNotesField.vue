<script setup lang="ts">
import { nextTick, ref } from 'vue'

import BaseField from '@/components/base/BaseField.vue'

/**
 * The operator's notes about this device — siting problems, whose dongle it
 * is, what still needs fixing. Published to Sentinel in `GET /api/v1/sdrs`
 * along with every other device field.
 *
 * Multi-line and optional: an empty value commits as `""`, clearing the note.
 * Commits on blur like every other field on the card.
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(defineProps<{ serverError?: string | null; disabled?: boolean }>(), {
  serverError: null,
  disabled: false,
})

const emit = defineEmits<{ commit: [string] }>()

/** Mirrors `DevicePatch.notes`'s `max_length`; the server re-validates regardless. */
const MAX_NOTES_LENGTH = 2000

const clientError = ref<string | null>(null)
const fieldRef = ref<InstanceType<typeof BaseField> | null>(null)

function validateAndCommit(): void {
  const trimmed = modelValue.value.trim()
  if (trimmed.length > MAX_NOTES_LENGTH) {
    clientError.value = `Notes must be ${MAX_NOTES_LENGTH} characters or fewer.`
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
    label="Notes"
    multiline
    :rows="3"
    :error="clientError ?? props.serverError"
    :disabled="props.disabled"
    @blur="validateAndCommit"
  />
</template>
