<script setup lang="ts">
import LiveRegion from '@/components/base/LiveRegion.vue'
import { useLiveAnnouncer } from '@/composables/useLiveAnnouncer'
import FleetView from '@/views/FleetView.vue'

const { politeMessage, assertiveMessage } = useLiveAnnouncer()
</script>

<template>
  <LiveRegion :polite-message="politeMessage" :assertive-message="assertiveMessage" />
  <FleetView />
</template>
