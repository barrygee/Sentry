<script setup lang="ts">
import { onScopeDispose, ref } from 'vue'

import BaseButton from '@/components/base/BaseButton.vue'

/**
 * Copies a short value to the clipboard and says so.
 *
 * Exists because the hotspot's gateway address is a value an operator has to
 * retype by hand into a *different application* on a *different machine* — the
 * one case in this app where getting a string out accurately matters more than
 * reading it.
 *
 * The confirmation is announced through a `role="status"` region that is
 * present from mount rather than created on click: a live region inserted into
 * the DOM already containing its text is frequently not announced at all, the
 * same trap `SerialFlashDialog` documents. Only the text changes.
 *
 * Failure is surfaced, not swallowed. `navigator.clipboard` rejects on an
 * insecure origin — which is precisely where Sentry lives, plain HTTP on a LAN
 * — so silently doing nothing would be the common case, not the rare one.
 */
const props = withDefaults(
  defineProps<{
    /** The text to place on the clipboard. */
    value: string
    /** Accessible name; should name what is being copied, not just "Copy". */
    accessibleName: string
    label?: string
  }>(),
  { label: 'Copy' },
)

type CopyOutcome = 'idle' | 'copied' | 'failed'

const outcome = ref<CopyOutcome>('idle')
let resetTimer: ReturnType<typeof setTimeout> | undefined

const RESET_DELAY_MS = 2500

async function copy(): Promise<void> {
  clearTimeout(resetTimer)
  try {
    await navigator.clipboard.writeText(props.value)
    outcome.value = 'copied'
  } catch {
    // Most likely an insecure origin or a denied permission. Either way the
    // operator needs to know to select the text themselves.
    outcome.value = 'failed'
  }
  resetTimer = setTimeout(() => {
    outcome.value = 'idle'
  }, RESET_DELAY_MS)
}

onScopeDispose(() => clearTimeout(resetTimer))
</script>

<template>
  <span class="inline-flex items-center gap-2">
    <BaseButton variant="ghost" :aria-label="accessibleName" @click="copy">
      {{ label }}
    </BaseButton>
    <!-- Always mounted; only its text changes (see the component doc). -->
    <span
      role="status"
      class="text-[11px]"
      :class="outcome === 'failed' ? 'text-signal-warn' : 'text-signal-muted'"
    >
      <template v-if="outcome === 'copied'">Copied</template>
      <template v-else-if="outcome === 'failed'">Copy it manually</template>
    </span>
  </span>
</template>
