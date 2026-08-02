import type { Config } from 'tailwindcss'

/**
 * Design tokens (architecture §9.5).
 *
 * Sentry matches **Sentinel's dark application chrome** — not the light
 * settings panel, which is a scoped exception inside Sentinel's own dark app.
 * Surfaces, accent and type are Sentinel's `assets/template.css` `:root`
 * values and its SDR panel, used as-is rather than approximated:
 *   --color-bg          #000000    -> ground.page
 *   SDR panel surface   #0a0d14    -> ground.panel   (its rgba(10,13,20,.92))
 *   --color-button-bg   #26292e    -> ground.raised  (control/slider fill)
 *   --color-border      rgba(255,255,255,.08) -> ground.hairline
 *   --color-accent      #c8ff00    -> signal.accent
 *
 * ## The accent is text again
 *
 * On the light palette lime was fill-only: 1.18:1 on white, unusable as text.
 * On black it is 17.76:1, and Sentinel uses it exactly that way — its active
 * segmented option is lime *text* on a `rgba(200,255,0,.12)` fill. So the
 * accent is free to be a label, a glyph, a border or a fill here, and the
 * separate text-safe stand-in the light theme needed is gone: `signal.ok` and
 * `signal.accent` are both `#c8ff00`, since a healthy Sentry chain and
 * Sentinel's live indicator are deliberately the same colour.
 *
 * ## Contrast, computed not eyeballed
 *
 * Verified against all three surfaces. `ground.raised` (#26292e) is the
 * lightest and therefore binds:
 *                     page    panel   raised(#26292e)
 *   ink.primary       16.83   15.57   11.69
 *   signal.accent/ok  17.76   16.44   12.34
 *   signal.warn       11.48   10.63    7.98
 *   signal.info       11.31   10.47    7.86
 *   signal.danger      6.52    6.03    4.53
 *   signal.muted       7.79    7.21    5.42
 *   signal.faint       4.94    4.57    3.43   (non-text; clears 3:1 everywhere)
 *
 * Sentinel's own `.sdr-field-label` is `rgba(255,255,255,.25)` — 2.25:1 on the
 * control fill, a clear AA failure that its own CSS acknowledges elsewhere
 * ("rgba(…, 0.18) only managed ~1.68:1"). Sentry's muted tone is lifted to
 * `#9a9ea3` instead of copying it. That, and `signal.danger` being Sentinel's
 * `#ff5050` only because it happens to clear 4.5:1, are the only places the
 * match is deliberately inexact.
 *
 * ## Type
 *
 * Barlow throughout, matching Sentinel: legends are Barlow 400 uppercase on a
 * wide tracking scale (its `.sdr-field-label` is 9px/400/0.18em), not the
 * condensed semibold Sentry used before. Numerics are Barlow with
 * `tabular-nums` rather than a monospace — Sentinel has no mono anywhere, and
 * Sentry's `font-mono` resolved to the system face (no JetBrains Mono ships in
 * either project), which is the most visible way the two drifted apart.
 * Barlow Condensed is kept only for the large readouts Sentinel also sets in
 * it. Note neither project ships BarlowCondensed-300, so Sentinel's `300` on
 * those readouts is synthesised; Sentry asks for 400 rather than chase it.
 *
 * Structural tokens (square corners, 22px card padding, 44px gutter, 1480px
 * measure) come from Sentinel's settings grid — see each below.
 */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        /** Surfaces, darkest-to-lightest: the page behind everything, the panels on it, the control fills inside those. */
        ground: {
          /** Page (Sentinel `--color-bg`). */
          page: '#000000',
          /** Panel/card surface (Sentinel's SDR panel, `rgba(10,13,20,.92)` flattened). */
          panel: '#0a0d14',
          /** Control and input fill (Sentinel `--color-button-bg`). */
          raised: '#26292e',
          /**
           * Hairline borders and dividers (Sentinel `--color-border`). Left as
           * rgba rather than flattened so it reads correctly on both the page
           * and the lighter panel — the same reason Sentinel keeps it rgba.
           */
          hairline: 'rgba(255, 255, 255, 0.08)',
        },
        /** Type colours. */
        ink: {
          /** Body and heading text (Sentinel `--color-text`, flattened). */
          primary: '#e6e6e6',
          /** Text that sits on a solid `signal.accent` fill. */
          'on-accent': '#0a0c10',
        },
        /** Semantic tones, named for meaning rather than hue. */
        signal: {
          /** The lime accent (Sentinel `--color-accent`). Text, border or fill — all are safe on black. */
          accent: '#c8ff00',
          /** Streaming / success. Identical to the accent by intent: Sentry's healthy chain is Sentinel's live indicator. */
          ok: '#c8ff00',
          /** Degraded, and any "are you sure" warning surface. */
          warn: '#ffb020',
          /** Error, and destructive actions (Sentinel's `#ff5050`). */
          danger: '#ff5050',
          /** Starting, connecting, and structural chrome (topology connectors). */
          info: '#3fd0e0',
          /** Secondary text: descriptions, field labels, idle-state labels. */
          muted: '#9a9ea3',
          /** Non-text: idle-state stripes and glyphs. Clears 3:1 on every surface but is not text-safe on `raised`. */
          faint: '#797e84',
        },
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        /** Large readouts only — Sentinel sets its frequency display in this. */
        condensed: ['"Barlow Condensed"', 'system-ui', 'sans-serif'],
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
        /** Large readouts (Sentinel's frequency display, `0.04em`). */
        readout: '0.04em',
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
        /** The settings grid's measure — stops cards stretching on ultrawide displays. */
        console: '1480px',
      },
    },
  },
  plugins: [],
} satisfies Config
