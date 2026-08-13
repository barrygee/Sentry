import { svgEl } from './svg.js'

/**
 * The ⊙ mark — Sentry's half of the identity it shares with Sentinel.
 *
 * The single definition of the geometry. It was drawn inline in `index.html`'s
 * header and nowhere else, which was fine while the header was the only place
 * it appeared; the sign-in screen made it two, and two hand-copied SVGs are how
 * one app ends up with two subtly different logos. The header and the sign-in
 * screen both mount this.
 *
 * **The ring is `currentColor`, the dot is the lime accent.** The mark has to
 * sit on the black header band *and* on the light sign-in canvas, where a white
 * ring would vanish — so the ring inherits from whatever it is mounted in and
 * each caller sets its own text colour. The dot never changes: it is the one
 * fixed point of the identity, and it clears contrast on both grounds.
 *
 * Proportions are the header's original, expressed as fractions of the viewBox
 * so a size change scales the whole mark rather than just cropping it.
 */
export interface LogoMarkProps {
  /** Rendered width and height in pixels. The mark is square. */
  size?: number
  /** Extra classes for the `<svg>` — positioning and the ring's text colour. */
  className?: string
}

// The original header drawing, as fractions of its 34.9 viewBox: a ring at
// 0.413 of the box with a 0.117 stroke, and a dot at 0.163.
const VIEWBOX = 34.9
const CENTRE = VIEWBOX / 2
const RING_RADIUS = VIEWBOX * 0.413
const RING_STROKE = VIEWBOX * 0.117
const DOT_RADIUS = VIEWBOX * 0.163

/** Builds the ⊙ mark. Static — it has no state and never updates. */
export function logoMark(props: LogoMarkProps = {}): SVGElement {
  const size = props.size ?? 26

  return svgEl(
    'svg',
    {
      attrs: {
        width: size,
        height: size,
        viewBox: `0 0 ${VIEWBOX} ${VIEWBOX}`,
        // Decorative: every caller pairs it with the "Sentry" wordmark as real
        // text, so announcing the mark as well would say the name twice.
        'aria-hidden': 'true',
        focusable: 'false',
      },
      class: props.className ?? '',
    },
    [
      svgEl('circle', {
        attrs: {
          cx: CENTRE,
          cy: CENTRE,
          r: RING_RADIUS,
          fill: 'none',
          stroke: 'currentColor',
          'stroke-width': RING_STROKE,
        },
      }),
      // `signal.accent` (#c8ff00), the same lime Sentinel's mark uses. The two
      // apps' marks are one identity rather than two drawings of it, which is
      // worth more here than reserving the accent purely for live state.
      svgEl('circle', {
        attrs: { cx: CENTRE, cy: CENTRE, r: DOT_RADIUS, fill: '#c8ff00' },
      }),
    ],
  )
}
