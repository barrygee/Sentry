<script setup lang="ts">
import AuthTokenPrompt from '@/components/auth/AuthTokenPrompt.vue'
import LiveRegion from '@/components/base/LiveRegion.vue'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import FleetView from '@/views/FleetView.vue'

const { politeMessage, assertiveMessage } = useLiveAnnouncer()
</script>

<template>
  <a
    href="#devices-heading"
    class="sr-only-focusable fixed left-2 top-2 z-[100] rounded-rack bg-ground-page px-3 py-2 font-condensed text-xs uppercase tracking-legend text-signal-amber"
  >
    Skip to devices
  </a>
  <LiveRegion :polite-message="politeMessage" :assertive-message="assertiveMessage" />
  <main class="flex min-h-full flex-col">
    <FleetView />
  </main>
  <AuthTokenPrompt />
</template>
