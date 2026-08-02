<script setup lang="ts">
/**
 * The single button primitive every control in the app composes from —
 * variants are style-only, never a reason to duplicate markup.
 *
 * Chrome follows Sentinel's settings buttons (`.ba-btn--ghost/primary/danger`):
 * 11px uppercase Barlow at 0.16em tracking, a 6px radius, and a flat fill
 * rather than an outline. `ghost` is the neutral grey wash, `primary` is the
 * solid lime accent behind near-black text (16.55:1 — the accent is only ever
 * a fill, see `tailwind.config.ts`), and `danger` is a red wash. The primary
 * hover `#d8ff33` is Sentinel's own value.
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
    'bg-signal-accent font-bold tracking-control text-ink-on-accent hover:bg-[#d8ff33] disabled:bg-ground-raised disabled:text-signal-muted',
  ghost: 'bg-ground-raised text-ink-primary hover:bg-ground-hairline disabled:opacity-40',
  danger: 'bg-signal-danger/10 text-signal-danger hover:bg-signal-danger/20 disabled:opacity-40',
} as const satisfies Record<'primary' | 'ghost' | 'danger', string>
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :class="[
      'inline-flex min-h-[44px] items-center justify-center gap-2 whitespace-nowrap rounded-control border-none px-[18px] font-condensed text-[11px] font-semibold uppercase tracking-heading transition-colors disabled:cursor-not-allowed sm:min-h-[38px]',
      variantClasses[props.variant],
    ]"
    @click="$emit('click', $event)"
  >
    <slot />
  </button>
</template>
