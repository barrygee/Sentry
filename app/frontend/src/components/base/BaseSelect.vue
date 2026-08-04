<script setup lang="ts">
import { computed, useId, ref } from 'vue'

/**
 * The single labelled-select primitive, matching `BaseField`'s stacked-field
 * geometry so a select and a text input sitting in the same form align on
 * their label and their text rather than merely on their box.
 *
 * A **native `<select>`**, deliberately, not a custom listbox. A native control
 * is keyboard-operable, screen-reader-correct, and usable with a phone's native
 * picker for free; a hand-rolled listbox would have to re-earn all three and
 * would almost certainly get typeahead, `aria-activedescendant` and touch
 * behaviour subtly wrong. The only thing it costs is control over the option
 * list's appearance, which is worth nothing here.
 *
 * Label/error/hint wiring is identical to `BaseField` — a real `<label for>`, an
 * error associated through `aria-describedby` and announced via `role="alert"`,
 * and `aria-invalid` while one is present — so the two are interchangeable to
 * assistive tech.
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(
  defineProps<{
    label: string
    /** The choices, in display order. `value` is what `modelValue` carries. */
    options: readonly { value: string; label: string }[]
    error?: string | null
    hint?: string | null
    disabled?: boolean
    /** Extra id(s) to merge into `aria-describedby`, for content rendered outside this component. */
    describedBy?: string | null
  }>(),
  {
    error: null,
    hint: null,
    disabled: false,
    describedBy: null,
  },
)

const fieldId = useId()
const errorId = `${fieldId}-error`
const hintId = `${fieldId}-hint`
const selectElement = ref<HTMLSelectElement | null>(null)

const resolvedDescribedBy = computed(() => {
  const ids = [props.hint ? hintId : null, props.error ? errorId : null, props.describedBy].filter(
    (id): id is string => id !== null,
  )
  return ids.length > 0 ? ids.join(' ') : undefined
})

defineExpose({
  focus: () => selectElement.value?.focus(),
})
</script>

<template>
  <div class="flex flex-col">
    <label
      :for="fieldId"
      class="mb-1.5 block select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary"
    >
      {{ label }}
    </label>
    <select
      :id="fieldId"
      ref="selectElement"
      v-model="modelValue"
      :disabled="disabled"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="resolvedDescribedBy"
      :class="[
        'min-h-[24px] w-full min-w-0 appearance-none rounded-rack border-none bg-transparent px-0 py-0 font-tabular text-[12.5px] font-normal leading-[24px] tracking-readout text-ink-primary outline-none transition-shadow',
        'shadow-[inset_0_-1px_0_theme(colors.ground.hairline)] focus:shadow-[inset_0_-2px_0_theme(colors.signal.accent)]',
        'disabled:cursor-not-allowed disabled:opacity-40',
        error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
      ]"
    >
      <!-- The option list is the browser's own, so it needs its own background:
           a transparent option inherits the page's black and renders as
           black-on-black in the native dropdown on several platforms. -->
      <option
        v-for="option in options"
        :key="option.value"
        :value="option.value"
        class="bg-ground-panel text-ink-primary"
      >
        {{ option.label }}
      </option>
    </select>
    <p v-if="hint && !error" :id="hintId" class="mt-2 text-[11px] text-signal-muted">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="mt-2 text-[11px] text-signal-danger" role="alert">
      {{ error }}
    </p>
  </div>
</template>
