<script setup lang="ts">
/**
 * The left icon rail, matching Sentinel's settings sidebar
 * (`#settings-sidebar` / `.settings-nav-item`): a 48px dark column of
 * full-width 40px buttons, the active one carrying a 2px accent left border
 * and a faint accent wash.
 *
 * One destination today — the SDR list — with a WiFi view planned. It is a
 * `<nav>` with a real list rather than a row of buttons so that adding the
 * second entry is a data change, and so assistive tech announces "1 of 2"
 * when it arrives.
 *
 * The single button is still rendered, and still marked current, rather than
 * hidden until there are two: a rail that appears the day a second view lands
 * would move every page's content sideways at that moment. The icon is
 * Sentinel's own SDR glyph from the same rail.
 */
interface RailDestination {
  /** Stable key, also the button's `aria-controls` target when views exist. */
  key: string
  /** Accessible name and tooltip text. */
  label: string
}

const DESTINATIONS: readonly RailDestination[] = [{ key: 'sdrs', label: 'SDR devices' }]

const activeKey = 'sdrs'
</script>

<template>
  <nav aria-label="Views" class="w-12 shrink-0 bg-ground-rail">
    <ul class="m-0 flex list-none flex-col p-0">
      <li v-for="destination in DESTINATIONS" :key="destination.key">
        <button
          type="button"
          class="flex h-10 w-full items-center justify-center border-l-2 text-ink-inverse transition-colors"
          :class="
            destination.key === activeKey
              ? 'border-signal-accent bg-signal-accent/[0.08] text-signal-accent'
              : 'border-transparent hover:bg-white/[0.06]'
          "
          :aria-current="destination.key === activeKey ? 'page' : undefined"
          :title="destination.label"
        >
          <span class="sr-only">{{ destination.label }}</span>
          <!-- Sentinel's SDR glyph, from the same rail. -->
          <svg
            width="19"
            height="19"
            viewBox="0 0 24 24"
            fill="none"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <line x1="6" y1="9" x2="18" y2="3" stroke="currentColor" stroke-width="1.6" />
            <rect
              x="3"
              y="9"
              width="18"
              height="12"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linejoin="miter"
              fill="none"
            />
            <circle cx="16" cy="15" r="2.6" stroke="currentColor" stroke-width="1.6" />
            <line x1="6" y1="13" x2="11" y2="13" stroke="currentColor" stroke-width="1.6" />
            <line x1="6" y1="17" x2="11" y2="17" stroke="currentColor" stroke-width="1.6" />
          </svg>
        </button>
      </li>
    </ul>
  </nav>
</template>
