<script setup lang="ts">
import { computed, ref, useId } from 'vue'

/**
 * The single labelled-text-input primitive: a real `<label for>`, an
 * inline error associated via `aria-describedby`, and `aria-invalid` set
 * whenever an error is present. `DeviceNameField`, `PortAssignmentField`
 * and any future form field compose this rather than re-implementing
 * label/error wiring (architecture §9.4 forms rule).
 *
 * Visually it is Sentinel's stacked field: a white 9px uppercase label above
 * its own flat, square input, with the accent underline drawn inside the input
 * on focus and a red one while invalid.
 *
 * The input matches Sentinel's search field (`.bfp-input-wrap`/`.bfp-input`):
 * a `rgba(0,0,0,.32)` scrim, 40px tall, white text at 0.1em with an accent
 * caret. It carries no horizontal padding, so the value starts on the same
 * vertical line as the label above it — with padding the text sat indented
 * past its own caption, which read as a misalignment rather than as inset. One deliberate difference — Sentinel uppercases its search text, which
 * suits a filter keyword but would misrepresent a device name the operator
 * typed, so the value keeps its own casing here.
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
  <div class="flex flex-col">
    <!-- Sentinel's stacked field (`.sdr-field-label` + its control): the label
         sits *above* the input as its own block — white, 9px, 0.18em, 8px of
         clearance — rather than inside the fill beside it. The input below is
         a flat square surface with no border.

         The focus underline is drawn inside the input and layers under the
         global focus ring rather than competing with it; the ring remains the
         focus indicator (architecture §9.5). It is the raw lime accent, as
         Sentinel draws it — 12.34:1 on this fill. -->
    <label
      :for="fieldId"
      class="mb-2 block select-none font-sans text-[9px] uppercase tracking-control text-white"
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
      class="min-h-[44px] w-full min-w-0 rounded-rack border-none bg-ground-field px-0 text-[12px] font-tabular tracking-label text-white caret-signal-accent outline-none transition-shadow focus:shadow-[inset_0_-2px_0_theme(colors.signal.accent)] disabled:cursor-not-allowed disabled:opacity-40 sm:min-h-[40px]"
      :class="error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : ''"
      @blur="emit('blur')"
    />
    <p v-if="hint && !error" :id="hintId" class="mt-2 text-[11px] text-signal-muted">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="mt-2 text-[11px] text-signal-danger" role="alert">
      {{ error }}
    </p>
  </div>
</template>
