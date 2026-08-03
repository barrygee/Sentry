<script setup lang="ts">
import AuthTokenPrompt from '@/components/auth/AuthTokenPrompt.vue'
import LiveRegion from '@/components/base/LiveRegion.vue'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import FleetHeader from '@/components/fleet/FleetHeader.vue'
import NavRail from '@/components/fleet/NavRail.vue'
import FleetView from '@/views/FleetView.vue'

const { politeMessage, assertiveMessage } = useLiveAnnouncer()
</script>

<template>
  <a
    href="#devices-heading"
    class="sr-only-focusable fixed left-2 top-2 z-[100] rounded-rack bg-signal-accent px-4 py-3 font-sans text-[9px] uppercase tracking-control text-ink-on-accent"
  >
    Skip to devices
  </a>
  <LiveRegion :polite-message="politeMessage" :assertive-message="assertiveMessage" />
  <!-- Sentinel's shell: a black bar across the top, a dark icon rail down the
       left, and the light body filling what is left. The rail sits beside the
       body rather than beneath the header so it starts below the bar, as its
       settings sidebar does. -->
  <div class="flex min-h-full flex-col bg-ground-page">
    <FleetHeader />
    <div class="flex flex-1 items-stretch">
      <NavRail />
      <main class="min-w-0 flex-1">
        <FleetView />
      </main>
    </div>
  </div>
  <AuthTokenPrompt />
</template>
