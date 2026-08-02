<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

/**
 * The single accessible modal primitive every dialog in the app composes
 * from — owns focus-trapping, `Escape`-to-dismiss, and restoring focus to
 * whichever control opened it, so no dialog has to reimplement modal
 * semantics itself. Callers provide the id of their own heading via
 * `labelledBy` and their body as the default slot.
 *
 * Visually the panel is a settings card scaled up (Sentinel `.settings-item`):
 * square, flat panel fill, 22px padding, over a blurred black scrim.
 *
 * `disableDismiss` suppresses `Escape` (and the caller is expected to also
 * disable its own close/cancel controls) while a destructive action is
 * already committed and in flight, so a stray keypress can never read as
 * "cancelling" hardware that is already being written to.
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    labelledBy: string
    disableDismiss?: boolean
  }>(),
  { disableDismiss: false },
)

const emit = defineEmits<{ close: [] }>()

const panelElement = ref<HTMLDivElement | null>(null)
let previouslyFocusedElement: HTMLElement | null = null

function focusableElements(): HTMLElement[] {
  if (!panelElement.value) {
    return []
  }
  const selector =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  return Array.from(panelElement.value.querySelectorAll<HTMLElement>(selector)).filter(
    (element) => element.offsetParent !== null,
  )
}

function requestClose(): void {
  if (props.disableDismiss) {
    return
  }
  emit('close')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.stopPropagation()
    requestClose()
    return
  }
  if (event.key !== 'Tab') {
    return
  }
  const focusable = focusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && active === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      previouslyFocusedElement = document.activeElement as HTMLElement | null
      void nextTick(() => {
        const [firstFocusable] = focusableElements()
        ;(firstFocusable ?? panelElement.value)?.focus()
      })
    } else {
      previouslyFocusedElement?.focus()
      previouslyFocusedElement = null
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
    >
      <!-- The static checker doesn't recognise `role="dialog"` as interactive, but a modal
           genuinely needs its own `keydown` handler here: it owns the Escape-to-dismiss
           behaviour and the Tab focus trap for everything inside it (architecture §9.4/§11). -->
      <!-- eslint-disable-next-line vuejs-accessibility/no-static-element-interactions -->
      <div
        ref="panelElement"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="labelledBy"
        tabindex="-1"
        class="flex max-h-full w-full max-w-lg flex-col gap-4 overflow-y-auto rounded-rack bg-ground-panel p-card outline-none"
        @keydown="onKeydown"
      >
        <slot />
      </div>
    </div>
  </Teleport>
</template>
