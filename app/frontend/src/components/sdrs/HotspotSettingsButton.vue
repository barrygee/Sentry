<script setup lang="ts">
import { useHotspotStore } from '@/stores/hotspot'

/**
 * The header's only control: opens the WiFi hotspot settings.
 *
 * Not a `BaseButton` — this is an icon affordance in a bare title bar, where
 * the button primitive's filled uppercase slab would read as a call to action
 * rather than a settings entry point. It still meets the same floor: a 44px
 * touch target, a visible focus ring from the global `:focus-visible` rule, and
 * an accessible name, since the glyph itself is `aria-hidden`.
 *
 * `aria-haspopup="dialog"` plus `aria-expanded` tell a screen-reader user that
 * this opens a modal and whether it is currently open — otherwise the dialog
 * appears with no indication of what produced it.
 */
const hotspotStore = useHotspotStore()
</script>

<template>
  <button
    type="button"
    class="inline-flex h-11 w-11 items-center justify-center rounded-rack border-none bg-transparent text-signal-muted transition-colors hover:text-ink-inverse"
    aria-label="WiFi hotspot settings"
    aria-haspopup="dialog"
    :aria-expanded="hotspotStore.dialogOpen"
    @click="hotspotStore.openDialog()"
  >
    <!-- A broadcast/hotspot mark rather than a gear: this button opens one
         specific thing, and naming it in the glyph beats a generic settings
         icon that implies a whole settings area that does not exist. -->
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10" cy="14" r="1.6" fill="currentColor" stroke="none" />
      <path d="M6.8 11.2a4.4 4.4 0 0 1 6.4 0" />
      <path d="M4.3 8.5a8 8 0 0 1 11.4 0" />
    </svg>
  </button>
</template>
