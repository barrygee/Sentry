<script setup lang="ts">
import { ref } from 'vue'

import AuthTokenPrompt from '@/components/auth/AuthTokenPrompt.vue'
import LiveRegion from '@/components/base/LiveRegion.vue'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import SdrsHeader from '@/components/sdrs/SdrsHeader.vue'
import NavRail from '@/components/sdrs/NavRail.vue'
import NavRailToggle from '@/components/sdrs/NavRailToggle.vue'
import SdrsView from '@/views/SdrsView.vue'

const { politeMessage, assertiveMessage } = useLiveAnnouncer()

/**
 * The rail's visibility lives here rather than inside `NavRail`, because the
 * control that flips it has to outlive the thing it hides: hiding the whole
 * rail would otherwise take the button with it and leave no way back.
 */
const RAIL_ID = 'nav-rail'
const isRailVisible = ref(true)
</script>

<template>
  <a
    href="#devices-heading"
    class="sr-only-focusable fixed left-2 top-2 z-[100] rounded-rack bg-signal-accent px-4 py-3 font-sans text-[10px] font-semibold uppercase tracking-control text-ink-on-accent"
  >
    Skip to devices
  </a>
  <LiveRegion :polite-message="politeMessage" :assertive-message="assertiveMessage" />
  <!-- Sentinel's shell: a black bar across the top, a dark icon rail down the
       left, and the light body filling what is left. The rail sits beside the
       body rather than beneath the header so it starts below the bar, as its
       settings sidebar does.

       The shell is exactly one viewport tall and the device list scrolls
       *inside* `main`, rather than the whole page scrolling. That is how
       Sentinel's chrome behaves, and it is what keeps the rail — and the
       show/hide control at its foot — on screen: with the page scrolling as a
       whole, that control sat at the bottom of the full device list and could
       only be reached by scrolling past every card.

       `h-full` rather than `h-screen`, riding the `html, body, #app { height:
       100% }` chain in `base.css`. `h-screen` measures the viewport directly
       and so ignores anything else in the document, which left the shell
       taller than its container and reintroduced a second, outer scrollbar. -->
  <div class="flex h-full flex-col overflow-hidden bg-ground-page">
    <SdrsHeader />
    <div class="flex min-h-0 flex-1 items-stretch">
      <!-- `v-show`, not `v-if`: the toggle's `aria-controls` has to keep
           pointing at a element that exists even while the rail is hidden. -->
      <NavRail v-show="isRailVisible" :id="RAIL_ID" />
      <!-- Rendered here, straight after the rail, so it keeps the rail's place
           in the tab order despite being positioned. -->
      <NavRailToggle
        class="fixed bottom-0 left-0 z-20"
        :expanded="isRailVisible"
        :controls="RAIL_ID"
        @toggle="isRailVisible = !isRailVisible"
      />
      <main class="min-w-0 flex-1 overflow-y-auto">
        <SdrsView />
      </main>
    </div>
  </div>
  <AuthTokenPrompt />
</template>
