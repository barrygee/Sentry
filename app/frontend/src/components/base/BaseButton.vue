<script setup lang="ts">
/**
 * The single button primitive every control in the app composes from —
 * variants are style-only, never a reason to duplicate markup.
 *
 * Chrome follows Sentinel's dark panel buttons (`.sdr-panel-btn`): square,
 * uppercase Barlow 700 on wide tracking, over a flat translucent-white wash
 * rather than an outline, brightening on hover. `ghost` is that neutral wash,
 * `danger` is a red one, and `primary` is the solid lime accent behind
 * near-black text (16.55:1) — Sentinel's commit-action treatment. The primary
 * hover `#d8ff33` is Sentinel's own value.
 *
 * Sentinel's own buttons are 28px tall at 9px type; Sentry's are larger
 * because these are the primary controls on a page rather than dense controls
 * inside a side panel, and the touch-target floor below applies to them.
 *
 * Height is 44px on touch-sized viewports and Sentinel's 38px from `sm` up:
 * the settings look is built around the shorter control, but shrinking a
 * button below a comfortable thumb target on a phone is not a trade worth
 * making for visual fidelity. Both clear WCAG 2.2 AA target size (24px).
 */
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
  }>(),
  {
    variant: 'ghost',
    type: 'button',
    disabled: false,
  },
)

defineEmits<{ click: [MouseEvent] }>()

const variantClasses = {
  primary:
    'bg-signal-accent font-bold text-ink-on-accent hover:bg-[#d8ff33] disabled:bg-white/[0.08] disabled:text-signal-muted',
  ghost:
    'bg-white/[0.08] font-bold text-signal-muted hover:bg-white/[0.12] hover:text-ink-primary disabled:opacity-30',
  danger:
    'bg-signal-danger/[0.12] font-bold text-signal-danger hover:bg-signal-danger/20 disabled:opacity-30',
} as const satisfies Record<'primary' | 'ghost' | 'danger', string>
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :class="[
      'inline-flex min-h-[44px] items-center justify-center gap-2 whitespace-nowrap rounded-rack border-none px-[18px] font-sans text-[9px] uppercase tracking-control transition-colors disabled:cursor-not-allowed sm:min-h-[38px]',
      variantClasses[props.variant],
    ]"
    @click="$emit('click', $event)"
  >
    <slot />
  </button>
</template>
