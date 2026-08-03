<script setup lang="ts">
import { computed, ref, useId } from 'vue'

/**
 * The single labelled-text-entry primitive — an `<input>`, or a `<textarea>`
 * when `multiline`: a real `<label for>`, an inline error associated via
 * `aria-describedby`, and `aria-invalid` set whenever an error is present.
 * `DeviceNameField`, `PortAssignmentField`, `DeviceAntennaField`,
 * `DeviceNotesField` and any future form field compose this rather than
 * re-implementing label/error wiring (architecture §9.4 forms rule).
 *
 * Visually it is Sentinel's stacked field, near its settings-card scale: an
 * 11px uppercase label above its own flat, square input
 * whose text is the 12.5px `.settings-item-desc` size, with the accent
 * underline drawn inside the input on focus and a red one while invalid.
 *
 * The input has no fill of its own and no padding, so it reads as a value on
 * the card rather than a box sitting on it, and its text starts on the same
 * vertical line as the label above. Its weight matches the read-only values it
 * sits beside, so an editable field and a fixed one differ only by being
 * editable.
 *
 * Its 6px label gap and 24px line box are shared with `DataCell` — that pairing
 * is what lets a field and a readout on the same row align on their text rather
 * than merely starting at the same height, so the two must always be changed
 * together. 24px is also the WCAG 2.2 AA target minimum, which the old 40px box
 * cleared comfortably and this one only meets.
 *
 * One deliberate difference — Sentinel uppercases its search text, which
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
    /**
     * Render a `<textarea>` instead of an `<input>`, for free text that runs
     * to more than one line (device notes). Everything else — the `<label
     * for>`, the `aria-describedby` wiring, `aria-invalid`, the focus
     * underline — is identical, which is exactly why this is a flag here
     * rather than a second component duplicating that wiring.
     */
    multiline?: boolean
    /** Visible rows when `multiline`; ignored otherwise. */
    rows?: number
    /** Extra id(s) to merge into `aria-describedby`, for content the caller renders outside this component. */
    describedBy?: string | null
  }>(),
  {
    error: null,
    hint: null,
    type: 'text',
    inputMode: 'text',
    disabled: false,
    multiline: false,
    rows: 3,
    describedBy: null,
  },
)

const emit = defineEmits<{ blur: [] }>()

const fieldId = useId()
const errorId = `${fieldId}-error`
const hintId = `${fieldId}-hint`
const inputElement = ref<HTMLInputElement | HTMLTextAreaElement | null>(null)

// Held in one place rather than repeated across the `<input>` and
// `<textarea>` branches below — the two controls are meant to be visually
// indistinguishable apart from height, and two copies of a class string this
// long would not stay that way.
const CONTROL_CLASSES =
  'min-h-[24px] w-full min-w-0 rounded-rack border-none bg-transparent px-0 text-[12.5px] font-normal leading-[24px] font-tabular tracking-readout text-ink-primary caret-ink-primary outline-none shadow-[inset_0_-1px_0_theme(colors.ground.hairline)] transition-shadow focus:shadow-[inset_0_-2px_0_theme(colors.signal.accent)] disabled:cursor-not-allowed disabled:opacity-40'

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
      class="mb-1.5 block select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary"
    >
      {{ label }}
    </label>
    <textarea
      v-if="multiline"
      :id="fieldId"
      ref="inputElement"
      v-model="modelValue"
      :rows="rows"
      :disabled="disabled"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="resolvedDescribedBy"
      :class="[
        CONTROL_CLASSES,
        'resize-y',
        error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
      ]"
      @blur="emit('blur')"
    />
    <input
      v-else
      :id="fieldId"
      ref="inputElement"
      v-model="modelValue"
      :type="type"
      :inputmode="inputMode"
      :disabled="disabled"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="resolvedDescribedBy"
      :class="[CONTROL_CLASSES, error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '']"
      @blur="emit('blur')"
    />
    <p v-if="hint && !error" :id="hintId" class="mt-2 text-[11px] text-signal-muted">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="mt-2 text-[11px] text-signal-danger" role="alert">
      {{ error }}
    </p>
  </div>
</template>
