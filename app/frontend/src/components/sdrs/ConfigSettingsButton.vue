<script setup lang="ts">
import { useConfigStore } from '@/stores/config'

/**
 * Opens the configuration export/import dialog.
 *
 * Sits beside `HotspotSettingsButton` and is built the same way — an icon
 * affordance in the title bar rather than a `BaseButton`, whose filled
 * uppercase slab would read as a call to action rather than a settings entry
 * point. Same floor applies: a 44px touch target, the global focus ring, and an
 * accessible name, since the glyph is `aria-hidden`.
 */
const configStore = useConfigStore()
</script>

<template>
  <button
    type="button"
    class="inline-flex h-11 w-11 items-center justify-center rounded-rack border-none bg-transparent text-signal-muted transition-colors hover:text-ink-inverse"
    aria-label="Configuration export and import"
    aria-haspopup="dialog"
    :aria-expanded="configStore.dialogOpen"
    @click="configStore.openDialog()"
  >
    <!-- A document with a down-arrow: this moves a configuration file in and
         out, which a gear would not say. -->
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M11.5 2.5H5.5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V6.5z" />
      <path d="M11.5 2.5v4h4" />
      <path d="M10 9.5v5" />
      <path d="M8 12.5 10 14.5 12 12.5" />
    </svg>
  </button>
</template>
