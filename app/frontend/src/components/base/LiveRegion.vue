<script setup lang="ts">
/**
 * The two live regions rendered once at app root (architecture §9.4): a
 * polite region for plug/unplug and state-change announcements, and an
 * assertive `role="alert"` region for errors and serial-flash outcomes.
 * Visually hidden but always present in the accessibility tree.
 */
defineProps<{
  politeMessage: string
  assertiveMessage: string
}>()
</script>

<template>
  <div class="sr-only" aria-live="polite" aria-atomic="true">{{ politeMessage }}</div>
  <div class="sr-only" role="alert" aria-atomic="true">{{ assertiveMessage }}</div>
</template>
