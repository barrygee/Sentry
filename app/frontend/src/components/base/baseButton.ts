import { classes, el } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { syncChildren } from './childrenSync.js'

/**
 * The single button primitive every control in the app composes from —
 * variants are style-only, never a reason to duplicate markup.
 *
 * Chrome follows Sentinel's dark panel buttons (`.sdr-panel-btn`): square,
 * uppercase Barlow 700 on wide tracking, over a flat translucent-white wash
 * rather than an outline, brightening on hover. `ghost` is that neutral wash,
 * `danger` is a red one, and `primary` is the solid lime accent behind
 * near-black text (16.55:1) — Sentinel's commit-action treatment. The primary
 * hover is `signal.accent-hover`, Sentinel's own lifted value. `quiet` is the same legend type with
 * no fill at all, for a secondary action that should not compete with the
 * controls around it — on a card whose only filled elements are its inputs, a
 * filled button reads as the loudest thing on screen regardless of its tone.
 * It sits at body-text brightness and turns red on hover: its only use is a
 * destructive trigger, and at rest it must be plainly distinguishable from its
 * own disabled state, which is muted grey — two shades of grey would have left
 * "available" and "unavailable" looking identical.
 *
 * Sentinel's own buttons are 28px tall at 9px type; Sentry's are larger
 * because these are the primary controls on a page rather than dense controls
 * inside a side panel, and the touch-target floor below applies to them.
 *
 * Disabled drops the tone rather than the opacity: every variant falls back to
 * a faint fill with muted-grey text. A 30% wash of red left "Forget device"
 * barely legible, which matters because that button is disabled *by design*
 * while a dongle is plugged in — the operator has to be able to read the thing
 * whose unavailability the card is explaining. Disabled controls are exempt
 * from WCAG 1.4.3, so this is legibility rather than compliance.
 *
 * Height is 44px on touch-sized viewports and Sentinel's 38px from `sm` up:
 * the settings look is built around the shorter control, but shrinking a
 * button below a comfortable thumb target on a phone is not a trade worth
 * making for visual fidelity. Both clear WCAG 2.2 AA target size (24px).
 */
export type BaseButtonVariant = 'primary' | 'ghost' | 'danger' | 'quiet' | 'inverse' | 'on-bright'

export interface BaseButtonProps {
  variant?: BaseButtonVariant
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  /** Forwarded to `aria-label`, for a button whose visible content alone is not its accessible name. */
  ariaLabel?: string | null
  onClick?: (event: MouseEvent) => void
  /** The button's content — text, or richer markup (an icon plus a label). */
  children: Child[]
  /**
   * Extra classes appended after the variant's.
   *
   * A prop rather than something a caller adds to `element.classList`, because
   * `update()` reassigns `className` wholesale — anything poked on from outside
   * survives exactly until the first re-render, which is the sort of bug that
   * looks like a styling flake. Passed through here it is reapplied every time.
   */
  extraClass?: string
}

const VARIANT_CLASSES = {
  // Matched to Sentinel's `.ba-btn--primary` field by field: `#c8ff00` fill,
  // `#0a0c10` text, 11px/700 at 0.18em, `12px 30px` padding, `#d8ff33` on hover.
  primary:
    'bg-signal-accent px-[30px] py-3 font-bold tracking-control text-ink-on-accent hover:bg-signal-accent-hover disabled:bg-ink-primary/[0.06] disabled:text-signal-muted',
  ghost:
    'px-[18px] font-semibold tracking-heading bg-ink-primary/[0.06] text-ink-primary hover:bg-ink-primary/[0.12] disabled:bg-ink-primary/[0.04] disabled:text-signal-muted',
  danger:
    'px-[18px] font-semibold tracking-heading bg-signal-danger/[0.10] text-signal-danger hover:bg-signal-danger/[0.18] disabled:bg-ink-primary/[0.04] disabled:text-signal-muted',
  quiet:
    'bg-transparent px-0 font-bold tracking-heading text-ink-primary hover:text-signal-danger disabled:text-signal-muted disabled:hover:text-signal-muted',
  inverse:
    'px-[18px] font-semibold tracking-heading bg-white/20 text-white hover:bg-white/30 disabled:bg-white/10 disabled:text-white/60',
  // The solid dark slab. Named for its first use — a button on the yellow
  // `warn` notice, where `inverse`'s white-on-translucent-white all but
  // disappears — but it is now also the commit action on the settings boxes,
  // where the accent fill read as a status colour rather than a control.
  // 11.3:1 on the yellow and 14:1 for its white text, so it carries either.
  'on-bright':
    'px-[18px] font-semibold tracking-heading bg-ink-primary text-white hover:bg-ink-primary/[0.88] disabled:bg-ink-primary/40 disabled:text-white/70',
} as const satisfies Record<BaseButtonVariant, string>

/**
 * Everything every button shares — deliberately **not** including font weight,
 * letter spacing, or horizontal padding.
 *
 * Those used to live here as `font-semibold tracking-heading px-[18px]`, and
 * every variant that wanted something else set its own alongside. Both then
 * applied, at equal specificity, and the winner was whichever Tailwind happened
 * to emit later in the stylesheet — which was the base. So `primary`'s
 * `font-bold tracking-control` and `quiet`'s `font-bold` were silently
 * discarded, and the commit action rendered at 600/0.16em where Sentinel's is
 * 700/0.18em.
 *
 * `px` was the same bug, found later and left in place at the time because the
 * variant is shared and correcting it reflows every quiet button at once:
 * `.px-0` is emitted before `.px-\[18px\]`, so every `quiet` button carried
 * 18px of padding it explicitly declared away. The three affected rows — the
 * passphrase reveal toggle, "Keep current password", and the device dialogs —
 * were checked together when it was fixed.
 *
 * Nothing in the source said so in either case. Each variant read as though it
 * worked. Keeping all three properties out of the shared string means a
 * variant's declaration is the only one, so it cannot lose.
 */
const BASE_CLASSES =
  'inline-flex min-h-[44px] items-center justify-center gap-2 whitespace-nowrap rounded-rack border-none font-sans text-[11px] uppercase transition-colors disabled:cursor-not-allowed sm:min-h-[38px]'

/** Builds a `BaseButton`. `update` mutates the same `<button>` in place. */
export function baseButton(props: BaseButtonProps): Component<BaseButtonProps> {
  let currentProps = props

  const button = el(
    'button',
    {
      attrs: { type: props.type ?? 'button', 'aria-label': props.ariaLabel ?? undefined },
      props: { disabled: props.disabled ?? false },
      class: classes(BASE_CLASSES, VARIANT_CLASSES[props.variant ?? 'ghost'], props.extraClass),
      on: {
        click: (event) => currentProps.onClick?.(event),
      },
    },
    props.children,
  )

  return {
    element: button,

    update(nextProps): void {
      currentProps = nextProps
      button.type = nextProps.type ?? 'button'
      button.disabled = nextProps.disabled ?? false
      if (nextProps.ariaLabel) {
        button.setAttribute('aria-label', nextProps.ariaLabel)
      } else {
        button.removeAttribute('aria-label')
      }
      button.className = classes(
        BASE_CLASSES,
        VARIANT_CLASSES[nextProps.variant ?? 'ghost'],
        nextProps.extraClass,
      )
      syncChildren(button, nextProps.children)
    },

    destroy(): void {
      // Only the click listener is attached, and it lives on `button` itself —
      // it is torn down automatically when the node is removed from the DOM.
    },
  }
}
