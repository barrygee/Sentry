import type { Config } from 'tailwindcss'

/**
 * "Patch Bay" design tokens (architecture §9.5).
 *
 * Sentry adopts Sentinel's settings section wholesale — its light palette,
 * card grid, square corners, flat fills and uppercase Barlow legends. The two
 * consoles are meant to read as one product, so the ground tones and the lime
 * accent are Sentinel's own values, not approximations:
 *   canvas  #f6f6f4   card  #ffffff   input fill #e8eaed
 *   accent  #c8ff00   text-on-accent  #0a0c10
 *
 * This replaced Sentry's original near-black "patch bay" theme, whose amber
 * accent existed to tell the two windows apart. That divergence is gone by
 * choice; what distinguishes Sentry now is its content, not its palette.
 *
 * ## The accent is a FILL, never text
 *
 * Lime `#c8ff00` is 1.18:1 on white — invisible as text and below the 3:1
 * non-text minimum, so it can never carry meaning on its own. It appears only
 * as a solid fill behind `ink.on-accent` (16.55:1): the primary button, the
 * active toggle, the heading dot, `PortLug`. This is exactly how Sentinel's
 * settings panel uses it. Wherever "the accent, as text" is needed — the
 * `streaming` state label, its card stripe, an OK status — use `signal.ok`,
 * the text-safe olive form.
 *
 * ## Contrast, computed not eyeballed
 *
 * Every semantic tone clears WCAG 2.2 AA (4.5:1) against all three grounds it
 * can land on, including the `raised` input fill, which is the darkest and so
 * the binding constraint:
 *                    canvas   card   raised(#e8eaed)
 *   ink.primary      13.96   15.11   12.54
 *   signal.muted      5.15    5.57    4.62   (secondary text, field labels)
 *   signal.ok         5.25    5.68    4.71   (streaming / success)
 *   signal.warn       5.48    5.93    4.92   (degraded)
 *   signal.danger     5.42    5.86    4.87   (error)
 *   signal.info       5.69    6.16    5.11   (starting / structural chrome)
 *   signal.faint      3.08    3.33    2.76   (NON-TEXT ONLY — see below)
 *
 * `signal.faint` is the one tone below the text threshold. It is the >=3:1
 * non-text minimum on canvas and card, for the idle-state card stripe and
 * glyph only; the matching state LABEL uses `signal.muted`. Never set it as
 * a text colour, and never use it on `raised` at all (2.76:1).
 *
 * Sentinel's own settings CSS runs its secondary text at rgba(16,19,29,.5)
 * and its muted labels at .35 — 3.49:1 and ~2.6:1. Those fail AA, so Sentry's
 * equivalents are darkened to the values above rather than copied exactly.
 * It is the one place the match is deliberately inexact.
 *
 * Structural tokens (square corners, the tracking scale, 22px card padding,
 * 44px gutter, 1480px measure) come from the same source — see each below.
 */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        /** Surfaces, lightest-to-flattest: the page behind everything, the cards on it, the fills inside those. */
        ground: {
          /** Page canvas (Sentinel `#settings-panel`). */
          page: '#f6f6f4',
          /** Card surface (Sentinel `.settings-item`). */
          panel: '#ffffff',
          /** Input and flat-data-row fill (Sentinel's `#e8eaed`). */
          raised: '#e8eaed',
          /** Hairline borders and dividers (Sentinel's rgba(16,19,29,.08), flattened). */
          hairline: '#e2e2df',
        },
        /** Type colours. */
        ink: {
          /** Body and heading text (Sentinel's rgba(16,19,29,.92), flattened). */
          primary: '#23262f',
          /** Text that sits on a solid `signal.accent` fill. */
          'on-accent': '#0a0c10',
        },
        /**
         * Semantic tones. Named for what they mean, not what they look like —
         * `ok` is an olive, not a lime, because the lime it stands in for is
         * fill-only (see the header comment).
         */
        signal: {
          /** The lime accent. FILL ONLY — never a text or border colour. */
          accent: '#c8ff00',
          /** Streaming / success / "applied". The text-safe form of the accent. */
          ok: '#4a7200',
          /** Degraded, and any "are you sure" warning surface. */
          warn: '#8a5a00',
          /** Error, and destructive actions. */
          danger: '#b8352a',
          /** Starting, connecting, and structural chrome (topology connectors). */
          info: '#0c6a84',
          /** Secondary text: descriptions, field labels, idle-state labels. */
          muted: '#66686e',
          /** NON-TEXT ONLY (3.08:1 on canvas): idle-state stripes and glyphs. */
          faint: '#8a8d92',
        },
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        condensed: ['"Barlow Condensed"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        /**
         * Square. Sentinel's settings section deliberately carries no radius
         * on its cards, inputs, rails and segmented controls; `rack` is the
         * token every panel-sized surface in Sentry uses, so squaring it here
         * squares the whole console in one place.
         */
        rack: '0px',
        /** Small status chips only (Sentinel `.tle-status-badge`). */
        chip: '4px',
        /** Buttons and inset notice boxes (Sentinel `.ba-btn--ghost`, `.settings-connectivity-warning`). */
        control: '6px',
      },
      /**
       * Sentinel's settings section runs a five-step tracking scale, tightening
       * as type gets larger. Every uppercase legend in Sentry maps onto one of
       * these steps rather than inventing its own value.
       */
      letterSpacing: {
        /** 13px card titles (Sentinel `.settings-item-label`). */
        label: '0.1em',
        /** Pre-existing Sentry legend step, kept for glyph-adjacent micro-labels. */
        legend: '0.08em',
        /** Search/section-heading type (Sentinel `#settings-search-input`). */
        caption: '0.14em',
        /** 21px section headings and ghost buttons (Sentinel `#settings-section-heading`). */
        heading: '0.16em',
        /** 10px control captions and primary buttons (Sentinel `.toggle-setting-label`). */
        control: '0.18em',
        /** Muted full-row group labels (Sentinel `.settings-group-label`). */
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
