<script setup lang="ts">
/**
 * An accessible on/off switch (`role="switch"`), used wherever a device's
 * `enabled` flag is edited. Native checkbox semantics under the hood so it
 * is keyboard-operable (Space toggles) without any custom key handling.
 *
 * Square track and thumb, matching Sentinel's switch geometry rather than the
 * usual pill: 46x25 track, 19px thumb. The tones are inverted from Sentinel's,
 * though — a black track throughout, with the thumb carrying the state in
 * accent lime when on and muted grey when off, rather than the whole track
 * filling with lime. The caption beside it uses the 9px legend step.
 */
const modelValue = defineModel<boolean>({ required: true })

withDefaults(
  defineProps<{
    /** Visible caption beside the switch. */
    label: string
    /**
     * Accessible name, when it must differ from the visible caption. It MUST
     * still contain `label` verbatim (WCAG 2.5.3 Label in Name) — the point is
     * to *add* disambiguating context, not to replace the visible text.
     *
     * Needed because several cards each render a switch whose visible caption
     * is identical ("Enable SDR"); without the device name appended, a screen
     * reader user tabbing the page hears the same name repeatedly with nothing
     * to tell the switches apart. Defaults to `label`.
     */
    accessibleName?: string | null
    disabled?: boolean
  }>(),
  { accessibleName: null, disabled: false },
)
</script>

<template>
  <label class="inline-flex min-h-[44px] cursor-pointer select-none items-center gap-3">
    <span class="font-sans text-[9px] uppercase tracking-control text-signal-muted">
      {{ label }}
    </span>
    <!-- Black track, accent thumb — the inverse of Sentinel's switch, which
         fills the whole track with lime when on.

         The track carries a hairline ring: black on the near-black card is
         about 1.1:1, so without it the control has no discernible boundary at
         all (WCAG 2.2 AA 1.4.11). The ring is a control boundary rather than
         decorative chrome, which is why it survives the card's otherwise
         borderless treatment. -->
    <span
      class="relative inline-flex h-[25px] w-[46px] shrink-0 items-center rounded-rack bg-ground-page ring-1 ring-inset ring-white/10"
    >
      <span
        class="absolute top-[3px] h-[19px] w-[19px] rounded-rack transition-[left,background-color]"
        :class="modelValue ? 'left-[24px] bg-signal-accent' : 'left-[3px] bg-signal-muted'"
      />
    </span>
    <input
      v-model="modelValue"
      type="checkbox"
      role="switch"
      class="sr-only"
      :disabled="disabled"
      :aria-label="accessibleName ?? label"
    />
  </label>
</template>
