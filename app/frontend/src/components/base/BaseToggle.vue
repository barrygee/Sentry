<script setup lang="ts">
/**
 * An accessible on/off switch (`role="switch"`), used wherever a device's
 * `enabled` flag is edited. Native checkbox semantics under the hood so it
 * is keyboard-operable (Space toggles) without any custom key handling.
 */
const modelValue = defineModel<boolean>({ required: true })

defineProps<{
  label: string
  disabled?: boolean
}>()
</script>

<template>
  <label class="inline-flex min-h-[44px] cursor-pointer items-center gap-3 select-none">
    <span
      class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-ground-hairline transition-colors"
      :class="modelValue ? 'bg-signal-amber/30' : 'bg-ground-raised'"
    >
      <span
        class="absolute h-4 w-4 rounded-full transition-transform"
        :class="modelValue ? 'translate-x-6 bg-signal-amber' : 'translate-x-1 bg-signal-slate'"
      />
    </span>
    <input
      v-model="modelValue"
      type="checkbox"
      role="switch"
      class="sr-only"
      :disabled="disabled"
      :aria-label="label"
    />
    <span class="font-condensed text-xs uppercase tracking-legend text-signal-slate">
      {{ label }}
    </span>
  </label>
</template>
