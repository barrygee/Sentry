<script setup lang="ts">
/**
 * An accessible on/off switch (`role="switch"`), used wherever a device's
 * `enabled` flag is edited. Native checkbox semantics under the hood so it
 * is keyboard-operable (Space toggles) without any custom key handling.
 *
 * Square track and thumb, matching Sentinel's settings switch
 * (`BaseToggleSwitch`) rather than the usual pill: 46x25 track, 19px thumb,
 * accent fill when on with a dark thumb, raised fill when off. The caption
 * beside it uses the 10px control-tracking legend Sentinel pairs with it.
 */
const modelValue = defineModel<boolean>({ required: true })

defineProps<{
  label: string
  disabled?: boolean
}>()
</script>

<template>
  <label class="inline-flex min-h-[44px] cursor-pointer select-none items-center gap-3">
    <!-- Off, the track is the same near-white as the surfaces around it, so it
         carries a `signal.faint` border (3.33:1 on a card) to keep the control's
         own boundary discernible — WCAG 2.2 AA 1.4.11. On, the solid accent
         fill is boundary enough and the border goes transparent. -->
    <span
      class="relative inline-flex h-[25px] w-[46px] shrink-0 items-center rounded-rack border transition-colors"
      :class="
        modelValue ? 'border-transparent bg-signal-accent' : 'border-signal-faint bg-ground-raised'
      "
    >
      <span
        class="absolute top-[2px] h-[19px] w-[19px] rounded-rack transition-[left,background-color]"
        :class="modelValue ? 'left-[23px] bg-ink-on-accent' : 'left-[2px] bg-signal-muted'"
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
    <span
      class="font-condensed text-[10px] font-semibold uppercase tracking-control text-signal-muted"
    >
      {{ label }}
    </span>
  </label>
</template>
