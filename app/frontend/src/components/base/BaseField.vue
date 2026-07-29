<script setup lang="ts">
import { computed, useId } from 'vue'

/**
 * The single labelled-text-input primitive: a real `<label for>`, an
 * inline error associated via `aria-describedby`, and `aria-invalid` set
 * whenever an error is present. `DeviceNameField`, `PortAssignmentField`
 * and any future form field compose this rather than re-implementing
 * label/error wiring (architecture §9.4 forms rule).
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(
  defineProps<{
    label: string
    error?: string | null
    hint?: string | null
    type?: 'text' | 'number'
    inputMode?: 'text' | 'numeric'
    disabled?: boolean
  }>(),
  {
    error: null,
    hint: null,
    type: 'text',
    inputMode: 'text',
    disabled: false,
  },
)

const emit = defineEmits<{ blur: [] }>()

const fieldId = useId()
const errorId = `${fieldId}-error`
const hintId = `${fieldId}-hint`

const describedBy = computed(() => {
  const ids = [props.hint ? hintId : null, props.error ? errorId : null].filter(
    (id): id is string => id !== null,
  )
  return ids.length > 0 ? ids.join(' ') : undefined
})
</script>

<template>
  <div class="flex flex-col gap-1">
    <label
      :for="fieldId"
      class="font-condensed text-xs uppercase tracking-legend text-signal-slate"
    >
      {{ label }}
    </label>
    <input
      :id="fieldId"
      v-model="modelValue"
      :type="type"
      :inputmode="inputMode"
      :disabled="disabled"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="describedBy"
      class="min-h-[44px] rounded-rack border border-ground-hairline bg-ground-raised px-3 font-mono text-sm font-mono-tabular text-[#e7e9ea] outline-none focus-visible:border-signal-amber disabled:opacity-40"
      @blur="emit('blur')"
    />
    <p v-if="hint && !error" :id="hintId" class="text-xs text-signal-slate">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="text-xs text-signal-red" role="alert">{{ error }}</p>
  </div>
</template>
