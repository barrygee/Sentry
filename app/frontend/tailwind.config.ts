import type { Config } from 'tailwindcss'

/**
 * Design tokens (architecture §9.5).
 *
 * Sentry uses **Sentinel's palette, unmodified**. Every colour below is a value
 * taken from Sentinel's own CSS — `assets/template.css` `:root`, its SDR panel,
 * and its Space/waterfall components — not an approximation or a hue picked to
 * sit alongside it:
 *   --color-bg         #000000                page
 *   SDR panel          #0a0d14                panel
 *   --color-button-bg  #26292e                control fill
 *   --color-border     rgba(255,255,255,.08)  hairline
 *   --color-text       rgba(255,255,255,.9)   primary text
 *   --color-accent     #c8ff00                accent
 *                      #ff5050                red
 *                      #ffb000                warning amber (SpaceFilter)
 *                      #00aaff                blue (SdrWaterfall trace)
 *
 * Greys are white-at-alpha rather than flat hex, as Sentinel writes them, so
 * they composite correctly over whichever surface hosts them.
 *
 * Earlier revisions of this file carried an invented amber (#ffb020) and cyan
 * (#3fd0e0) held over from Sentry's retired "Patch Bay" theme. Sentinel has
 * neither; both are now its own values.
 *
 * ## Contrast
 *
 * Verified against all three surfaces, with the #26292e control fill binding as
 * the lightest. Every token clears WCAG 2.2 AA (4.5:1) for text:
 *                     page    panel   fill
 *   ink.primary       16.83   15.57   12.11
 *   signal.accent/ok  17.76   16.44   12.34
 *   signal.warn       11.46   10.61    7.97
 *   signal.info        8.19    7.58    5.69
 *   signal.danger      6.52    6.03    4.53
 *   signal.muted       7.19    6.66    4.79
 *   signal.faint       5.36    4.96    3.63   (non-text; clears 3:1 everywhere)
 *
 * One deliberate deviation: Sentinel's dimmest label step is
 * `rgba(255,255,255,.25)` (`.sdr-field-label`), which is 2.25:1 on the control
 * fill and fails AA — its own CSS flags the same problem elsewhere ("rgba(…,
 * 0.18) only managed ~1.68:1"). `signal.muted` uses `.5` instead, the alpha
 * Sentinel uses for its panel buttons, so field labels here read one step
 * brighter than its dimmest. Everything else matches exactly.
 *
 * ## Type
 *
 * Barlow throughout, matching Sentinel, on its single 9px/0.18em legend step
 * split by weight: 700 for section titles and buttons, 400 for field labels.
 * Numerics are Barlow with `tabular-nums`; neither app uses a monospace.
 * Barlow Condensed is reserved for card titles and large readouts. The wordmark
 * is Inter 500 at -1.5% tracking — what Sentinel's logo.svg uses, and nothing
 * else in either app.
 *
 * Structural tokens (square corners, 22px card padding, 860px measure) follow.
 */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        /** Surfaces. Sentinel's own, unmodified. */
        ground: {
          /** `--color-bg`. */
          page: '#000000',
          /** Its SDR panel surface. */
          panel: '#0a0d14',
          /** `--color-button-bg` — control fills, slider tracks, input rows. */
          raised: '#26292e',
          /** `--color-border`. */
          hairline: 'rgba(255, 255, 255, 0.08)',
        },
        /** Type colours. Sentinel writes every grey as white-at-alpha rather than a flat hex, so these do too — they then composite correctly on any surface. */
        ink: {
          /** `--color-text`. */
          primary: 'rgba(255, 255, 255, 0.9)',
          /** Text on a solid `signal.accent` fill. */
          'on-accent': '#0a0c10',
        },
        /** Semantic tones, every one a value Sentinel uses. */
        signal: {
          /** `--color-accent`. */
          accent: '#c8ff00',
          /** Streaming / success. The accent — Sentry's healthy chain is Sentinel's live indicator. */
          ok: '#c8ff00',
          /** Degraded. Sentinel's warning amber (`SpaceFilter`, `SpacePasses`). */
          warn: '#ffb000',
          /** Error and destructive actions. Sentinel's red. */
          danger: '#ff5050',
          /** Starting / connecting. Sentinel's blue (`SdrWaterfall` trace). */
          info: '#00aaff',
          /** Secondary text: field labels, button text, descriptions. Sentinel's control-label grey. */
          muted: 'rgba(255, 255, 255, 0.5)',
          /** Non-text: idle-state glyphs. */
          faint: 'rgba(255, 255, 255, 0.4)',
        },
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        /** Large readouts and card titles — Sentinel sets its frequency display and station name in this. */
        condensed: ['"Barlow Condensed"', 'system-ui', 'sans-serif'],
        /** The wordmark only. Sentinel's logo.svg is Inter 500; nothing else in either app uses it. */
        wordmark: ['Inter', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        /**
         * Square. Sentinel's settings section deliberately carries no radius
         * on its cards, inputs, rails and segmented controls; `rack` is the
         * token every panel-sized surface in Sentry uses, so squaring it here
         * squares the whole console in one place.
         */
        rack: '0px',
        /** Small status chips only. */
        chip: '4px',
      },
      /**
       * Tracking widens as type gets smaller — Sentinel's dark chrome runs its
       * 9px field labels at 0.18em and its large readouts at 0.04em. Every
       * uppercase legend in Sentry maps onto one of these steps rather than
       * inventing its own value.
       */
      letterSpacing: {
        /** The wordmark's negative tracking (Sentinel's logo.svg, -1.5%). */
        wordmark: '-0.015em',
        /** Large readouts (Sentinel's frequency display, `0.04em`). */
        readout: '0.04em',
        /** Data-cell values and card titles (Sentinel `.ba-data-cell-value`, its station name). */
        data: '0.06em',
        /** Glyph-adjacent micro-labels. */
        legend: '0.08em',
        /** Card titles. */
        label: '0.1em',
        /** Buttons and inline chips (Sentinel `.sdr-panel-btn`, `.sdr-scan-btn`). */
        caption: '0.14em',
        /** Section headings. */
        heading: '0.16em',
        /** 9-10px field labels — Sentinel's dominant legend step (`.sdr-field-label`). */
        control: '0.18em',
        /** Muted full-row group labels. */
        group: '0.22em',
      },
      spacing: {
        /** Card interior padding (Sentinel `.settings-item`). */
        card: '22px',
        /** Page gutter at `md` and up (Sentinel's 44px `#settings-body` padding). */
        gutter: '44px',
      },
      maxWidth: {
        /** The device stack's measure (Sentinel's 860px for its wide settings controls). */
        stack: '860px',
      },
    },
  },
  plugins: [],
} satisfies Config
