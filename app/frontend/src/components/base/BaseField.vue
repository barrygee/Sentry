<script setup lang="ts">
import { computed, ref, useId } from 'vue'

/**
 * The single labelled-text-input primitive: a real `<label for>`, an
 * inline error associated via `aria-describedby`, and `aria-invalid` set
 * whenever an error is present. `DeviceNameField`, `PortAssignmentField`
 * and any future form field compose this rather than re-implementing
 * label/error wiring (architecture §9.4 forms rule).
 *
 * Visually it is Sentinel's settings input shell: one flat, square surface
 * holding a small uppercase label chip and the input side by side, with the
 * accent underline drawn inside the row on focus and a red one while invalid.
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
  <div class="flex flex-col gap-1.5">
    <!-- Sentinel's labelled-input shell (`.settings-location-row`): the label
         sits inside the field's own flat fill rather than floating above it,
         and the whole row shares one square surface. The underlines are drawn
         inside the row and layer under the global focus ring rather than
         competing with it — the ring remains the focus indicator
         (architecture §9.5). The underline is the raw lime accent, as
         Sentinel draws it — on this dark fill it is 12.34:1 and genuinely
         visible, unlike on the light theme where it had to be substituted. -->
    <div
      class="flex items-stretch overflow-hidden rounded-rack bg-ground-raised transition-shadow focus-within:shadow-[inset_0_-2px_0_theme(colors.signal.accent)]"
      :class="[
        error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
        disabled ? 'opacity-40' : '',
      ]"
    >
      <label
        :for="fieldId"
        class="flex shrink-0 select-none items-center px-3 font-sans text-[9px] uppercase tracking-control text-signal-muted"
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
        class="min-h-[44px] w-full min-w-0 flex-1 border-none bg-transparent px-3 text-sm font-tabular text-ink-primary outline-none disabled:cursor-not-allowed sm:min-h-[38px]"
        @blur="emit('blur')"
      />
    </div>
    <p v-if="hint && !error" :id="hintId" class="text-[11px] text-signal-muted">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="text-[11px] text-signal-danger" role="alert">
      {{ error }}
    </p>
  </div>
</template>
