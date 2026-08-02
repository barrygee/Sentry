<script setup lang="ts">
import LogoMark from '@/components/base/LogoMark.vue'

/**
 * The console's title bar: Sentinel's ⊙ mark and wordmark, nothing else.
 *
 * Both are matched to Sentinel's `assets/logo.svg` rather than approximated.
 * That file sets "SENTINEL" in **Inter 500 at -1.5% tracking** — not Barlow,
 * which is the app's face everywhere else — and converts it to paths so it
 * needs no font at runtime. Sentry's wordmark has to say something different,
 * so it stays live text and vendors the one Inter weight (`assets/fonts.css`).
 *
 * The sizes below are derived from that artboard, not eyeballed. At the 26px
 * mark height Sentinel renders (`#nav` in its `template.css`), the artboard
 * scales by 26/34.9, so its 22.5-unit cap height lands at 16.8px on screen.
 * Inter's cap height is 1490/2048 em, giving a 23px font size. The 8px gap is
 * its 11.35-unit gap between the ring's outer edge and the wordmark's start,
 * at that same scale.
 *
 * The lockup is centred, unlike Sentinel's, which sits left in its nav bar.
 * Sentinel shares that bar with domain links and a settings gear; Sentry's
 * header holds nothing else, and the content below it is a centred column, so
 * centring the mark keeps the page on one axis.
 *
 * The header carried an "N / M streaming" counter, a "SDR Fleet Manager"
 * subtitle and a live-connection pill. All three are gone at the owner's
 * request. Note the consequence: nothing on the page now reports whether the
 * SSE stream is alive, so a stalled console looks identical to a healthy one.
 */
</script>

<template>
  <header class="flex h-[68px] shrink-0 items-center justify-center gap-2 bg-ground-page px-5">
    <LogoMark :size="26" />
    <h1
      class="m-0 font-wordmark text-[23px] font-medium uppercase leading-none tracking-wordmark text-white"
    >
      Sentry
    </h1>
  </header>
</template>
