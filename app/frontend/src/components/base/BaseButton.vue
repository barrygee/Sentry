<script setup lang="ts">
/**
 * The single button primitive every control in the app composes from —
 * variants are style-only, never a reason to duplicate markup.
 */
withDefaults(
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

const variantClasses: Record<'primary' | 'ghost' | 'danger', string> = {
  primary: 'bg-signal-amber text-ground-page hover:bg-[#ffc04d] disabled:bg-ground-hairline',
  ghost:
    'bg-transparent text-[#e7e9ea] border border-ground-hairline hover:border-signal-amber disabled:opacity-40',
  danger: 'bg-transparent text-signal-red border border-signal-red hover:bg-signal-red/10',
}
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :class="[
      'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-rack px-4 font-condensed text-sm font-semibold uppercase tracking-legend transition-colors disabled:cursor-not-allowed',
      variantClasses[variant],
    ]"
    @click="$emit('click', $event)"
  >
    <slot />
  </button>
</template>
