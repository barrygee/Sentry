<script setup lang="ts">
import LogoMark from '@/components/base/LogoMark.vue'

/**
 * The top bar: Sentinel's `#nav` — a full-width black band, 68px tall, with
 * the ⊙ mark and wordmark at the left. Black regardless of the light body
 * beneath it, as Sentinel's is.
 *
 * Both marks match Sentinel's `assets/logo.svg` rather than approximating it.
 * That file sets "SENTINEL" in **Inter 500 at -1.5% tracking** — not Barlow,
 * which is the app's face everywhere else — and converts it to paths so it
 * needs no font at runtime. Sentry's wordmark has to say something different,
 * so it stays live text and vendors the one Inter weight (`assets/fonts.css`).
 *
 * Sizes are derived from that artboard, not eyeballed: at the 26px mark height
 * Sentinel renders, the artboard scales by 26/34.9, putting its 22.5-unit cap
 * height at 16.8px on screen. Inter's cap height is 1490/2048 em, giving a 23px
 * font size. The 8px gap is its own 11.35-unit gap at that scale.
 */
</script>

<template>
  <header class="flex h-[68px] shrink-0 items-center gap-2 bg-ground-header pl-[10px] pr-[22px]">
    <LogoMark :size="26" />
    <h1
      class="m-0 font-wordmark text-[23px] font-medium uppercase leading-none tracking-wordmark text-ink-inverse"
    >
      Sentry
    </h1>
  </header>
</template>
