<script setup lang="ts">
import { computed, ref, useId } from 'vue'

/**
 * The single labelled-text-input primitive: a real `<label for>`, an
 * inline error associated via `aria-describedby`, and `aria-invalid` set
 * whenever an error is present. `DeviceNameField`, `PortAssignmentField`
 * and any future form field compose this rather than re-implementing
 * label/error wiring (architecture §9.4 forms rule).
 *
 * Exposes `focus()` so a caller whose blur-triggered validation just failed
 * can return focus to the input — otherwise a commit-on-blur error leaves
 * focus wherever the operator tabbed to next, and a screen-reader user never
 * hears which field it was about.
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
    /** Extra id(s) to merge into `aria-describedby`, for content the caller renders outside this component. */
    describedBy?: string | null
  }>(),
  {
    error: null,
    hint: null,
    type: 'text',
    inputMode: 'text',
    disabled: false,
    describedBy: null,
  },
)

const emit = defineEmits<{ blur: [] }>()

const fieldId = useId()
const errorId = `${fieldId}-error`
const hintId = `${fieldId}-hint`
const inputElement = ref<HTMLInputElement | null>(null)

const resolvedDescribedBy = computed(() => {
  const ids = [props.hint ? hintId : null, props.error ? errorId : null, props.describedBy].filter(
    (id): id is string => id !== null,
  )
  return ids.length > 0 ? ids.join(' ') : undefined
})

defineExpose({
  focus: () => inputElement.value?.focus(),
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
      ref="inputElement"
      v-model="modelValue"
      :type="type"
      :inputmode="inputMode"
      :disabled="disabled"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="resolvedDescribedBy"
      class="min-h-[44px] rounded-rack border border-ground-hairline bg-ground-raised px-3 font-mono text-sm font-mono-tabular text-[#e7e9ea] outline-none focus-visible:border-signal-amber disabled:opacity-40"
      @blur="emit('blur')"
    />
    <p v-if="hint && !error" :id="hintId" class="text-xs text-signal-slate">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="text-xs text-signal-red" role="alert">{{ error }}</p>
  </div>
</template>
