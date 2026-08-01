import type { Config } from 'tailwindcss'

/**
 * "Patch Bay" design tokens (architecture §9.5).
 *
 * Sentry inherits Sentinel's near-black ground and Barlow type family so the
 * two operator consoles read as siblings, but its primary accent is signal
 * amber (`#ffb020`) rather than Sentinel's lime — the one deliberate
 * divergence that lets an operator tell the two windows apart at a glance.
 * Lime is reserved exclusively for the `streaming` device state, so a
 * healthy Sentry chain deliberately rhymes with Sentinel's live indicator.
 *
 * Contrast verified against the `#0a0b0c` page ground (WCAG 2.2 AA, computed
 * via the relative-luminance formula, not eyeballed):
 *   amber            #ffb020 on #0a0b0c -> 10.77:1 (text-safe)
 *   lime             #c8ff00 on #0a0b0c -> 16.66:1 (text-safe)
 *   red              #ff5050 on #0a0b0c ->  6.11:1 (text-safe)
 *   cyan             #3fd0e0 on #0a0b0c -> 10.61:1 (text-safe)
 *   slate            #8b9296 on #0a0b0c ->  6.24:1 (text-safe — use for the
 *                                          "stopped"/"detected" state LABEL)
 *   slateMuted       #5c6467 on #0a0b0c ->  3.26:1 (>=3:1 non-text minimum —
 *                                          use only for the state STRIPE/glyph,
 *                                          never for text)
 *
 * amber also verified against every panel surface it's used on, since
 * `JackPair`/`PortLug` sit on raised/panel backgrounds, not the page ground
 * directly:
 *   amber            #ffb020 on panel   #141617 ->  9.93:1
 *   amber            #ffb020 on raised  #1b1e1f ->  9.17:1
 *   amber            #ffb020 on hairline #242829 ->  8.14:1
 *
 * Phase 2C rebalanced amber to be the interface's dominant accent (it had
 * regressed to appearing only in the wordmark and the enable toggle, with
 * cyan dominating everywhere else) — `JackPair`'s IQ/CTRL labels and the
 * topology tree's `PortLug` port markers moved from cyan to amber, since
 * together they are the most-repeated element on screen. Cyan remains for
 * secondary/structural chrome (topology connector lines, the "USB Topology"
 * heading, the "connecting" connection state) so the palette still reads as
 * two colours. Lime stays exclusive to the `streaming` device state.
 */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        ground: {
          page: '#0a0b0c',
          panel: '#141617',
          raised: '#1b1e1f',
          hairline: '#242829',
        },
        signal: {
          amber: '#ffb020',
          lime: '#c8ff00',
          red: '#ff5050',
          cyan: '#3fd0e0',
          slate: '#8b9296',
          slateMuted: '#5c6467',
        },
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        condensed: ['"Barlow Condensed"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        rack: '2px',
      },
      letterSpacing: {
        legend: '0.08em',
      },
    },
  },
  plugins: [],
} satisfies Config
