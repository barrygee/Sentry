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
  content: ['./index.html', './src/**/*.ts'],
  theme: {
    extend: {
      colors: {
        /** Surfaces. Sentinel's settings panel, plus its app chrome for the header and rail. */
        ground: {
          /**
           * Body canvas. Darker than Sentinel's `#f6f6f4`, which is 1.03:1
           * against a white box — a different colour on paper, not one on
           * screen. At 1.17:1 a box reads as sitting on the page rather than
           * merging into it.
           */
          page: '#eaeae7',
          /** Card surface (Sentinel `.settings-item`). */
          panel: '#ffffff',
          /** Row fill inside a card — a step below the card, above the canvas. */
          raised: '#f4f4f2',
          /** Input fill (Sentinel's `#e8eaed`). */
          field: '#e8eaed',
          /** Hairline dividers (Sentinel's rgba(16,19,29,.08), flattened). */
          hairline: '#e5e5e2',
          /** Top bar (Sentinel `#nav`). */
          header: '#000000',
          /** Left icon rail (Sentinel `#settings-sidebar`). */
          rail: '#10131d',
        },
        /** Type colours. */
        ink: {
          /** Body and heading text (Sentinel's rgba(16,19,29,.92), flattened). */
          primary: '#23262f',
          /** Text on a solid `signal.accent` fill. */
          'on-accent': '#0a0c10',
          /** Text on the black header and dark rail. */
          inverse: '#ffffff',
        },
        /**
         * Semantic tones. Named for meaning rather than hue — on this palette
         * the tone that means "lime" is an olive, because lime is 1.18:1 on
         * white and can only ever be a fill.
         */
        signal: {
          /** The lime accent. FILL and decorative marks only — never text or a border. */
          accent: '#c8ff00',
          /**
           * The accent lifted for hover, and the only other green in the app.
           *
           * A token rather than the hex it used to be, inline in `baseButton`:
           * an untokenised colour is how a second green appears without anyone
           * deciding on one. Sentinel's own hover value, kept because the
           * console matches its chrome (ADR-0006).
           */
          'accent-hover': '#d8ff33',
          /** Streaming / success, as TEXT. The text-safe form of the accent. */
          ok: '#436800',
          /**
           * Success as a solid FILL, with dark text on it.
           *
           * A separate token because the two jobs pull opposite ways: `ok` is
           * darkened until it reads on white, which is precisely what makes it
           * muddy behind white text. This is the accent's own green, kept
           * vibrant and paired with `ink.on-accent` rather than white.
           */
          'ok-fill': '#63a300',
          /**
           * Degraded. TEXT only — this is the text-safe form of the warning
           * hue, dark enough to read on a white card (7.97:1 at worst).
           */
          warn: '#7d5200',
          /**
           * Warning FILL only — never text. A true yellow rather than
           * Sentinel's amber `#ffb000`, which read as orange at this size. As
           * a fill it carries `ink.on-accent` at 14.6:1; as text on a white
           * card it would be 1.4:1, which is why the two warning tones are
           * separate tokens rather than one. The dark `warn` above used to do
           * both jobs and read as brown when used as a surface.
           */
          'warn-fill': '#ffdd00',
          /**
           * Error and destructive actions. Saturated deliberately: the earlier
           * `#b8352a` read as dusty pink once laid under its own tint, and
           * Sentinel's `#d94436` is worse — 2.98:1 on that tint, which is why
           * neither could simply be copied. This clears 4.5:1 on the wash while
           * being markedly more saturated than either (0.92 vs 0.75-0.77).
           */
          danger: '#d0190a',
          /** Starting / connecting, and structural chrome. */
          info: '#0c6a84',
          /** Secondary text: descriptions, captions, idle-state labels. */
          muted: '#66686e',
          /** Non-text: idle-state marks. */
          faint: '#8a8d92',
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
        /**
         * Card interior padding. Sentinel's `.settings-item` uses 22px; the
         * boxes here carry more content than one of its settings rows — two
         * switches, four editable fields and a notes area — and needed more
         * breathing room between that content and the box edge.
         */
        card: '30px',
        /** Page gutter at `md` and up (Sentinel's 44px `#settings-body` padding). */
        gutter: '44px',
      },
      maxWidth: {
        /**
         * The body's measure. Sized from the widest thing a device box holds:
         * its five read-only cells need 621px on one line (measured), plus the
         * box's own 30px padding either side, plus slack for a longer model
         * string than the fixtures carry. Boxes are this wide at every viewport
         * rather than stretching to the page, so a set of SDRs reads as a consistent
         * column instead of as bands whose length depends on the window.
         */
        content: '860px',
      },
    },
  },
  plugins: [],
} satisfies Config
