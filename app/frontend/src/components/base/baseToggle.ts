import { classes, el, setAttribute, setText } from '../../core/dom.js'
import type { Component } from '../../core/component.js'

/**
 * An accessible on/off switch (`role="switch"`), used wherever a device's
 * `enabled` flag is edited. Native checkbox semantics under the hood so it
 * is keyboard-operable (Space toggles) without any custom key handling.
 *
 * Square track and thumb, matching Sentinel's switch geometry rather than the
 * usual pill: 46x25 track, 19px thumb. The tones are inverted from Sentinel's,
 * though — a black track throughout, with the thumb carrying the state in
 * accent lime when on and muted grey when off, rather than the whole track
 * filling with lime. The caption beside it uses the 9px legend step.
 */
export interface BaseToggleProps {
  value: boolean
  onChange: (value: boolean) => void
  /** Visible caption beside the switch. */
  label: string
  /**
   * Accessible name, when it must differ from the visible caption. It MUST
   * still contain `label` verbatim (WCAG 2.5.3 Label in Name) — the point is
   * to *add* disambiguating context, not to replace the visible text.
   *
   * Needed because several cards each render a switch whose visible caption
   * is identical ("Enable SDR"); without the device name appended, a screen
   * reader user tabbing the page hears the same name repeatedly with nothing
   * to tell the switches apart. Defaults to `label`.
   */
  accessibleName?: string | null
  disabled?: boolean
}

/** Builds a `BaseToggle`. `update` mutates the same checkbox in place. */
export function baseToggle(props: BaseToggleProps): Component<BaseToggleProps> {
  let currentProps = props

  const captionSpan = el(
    'span',
    { class: 'font-sans text-[10px] font-semibold uppercase tracking-control text-ink-primary' },
    [props.label],
  )

  const thumb = el('span', {
    class: classes(
      'absolute top-[3px] h-[19px] w-[19px] rounded-rack transition-[left,background-color]',
      props.value ? 'left-[24px] bg-ink-on-accent' : 'left-[3px] bg-ground-panel',
    ),
  })

  // Black track, accent thumb — the inverse of Sentinel's switch, which
  // fills the whole track with lime when on.
  //
  // The track is unbordered and near-invisible against the card, so the
  // thumb is what identifies the control and carries its state: lime at
  // 17.8:1 when on, muted grey at 7.2:1 when off. WCAG 2.2 AA 1.4.11 asks
  // that the visual information needed to identify a component clears
  // 3:1 — the thumb does that on its own; the track never did.
  const track = el(
    'span',
    {
      class: classes(
        'relative inline-flex h-[25px] w-[46px] shrink-0 items-center rounded-rack transition-colors',
        props.value ? 'bg-signal-accent' : 'bg-ink-primary/[0.14]',
      ),
    },
    [thumb],
  )

  const checkbox = el('input', {
    attrs: {
      type: 'checkbox',
      role: 'switch',
      disabled: props.disabled ?? false,
      'aria-label': props.accessibleName ?? props.label,
    },
    class: 'sr-only',
    props: { checked: props.value },
    on: {
      change: () => currentProps.onChange(checkbox.checked),
    },
  }) as HTMLInputElement

  const root = el(
    'label',
    { class: 'inline-flex min-h-[44px] cursor-pointer select-none items-center gap-3' },
    [captionSpan, track, checkbox],
  )

  return {
    element: root,

    update(nextProps): void {
      currentProps = nextProps

      setText(captionSpan, nextProps.label)

      track.className = classes(
        'relative inline-flex h-[25px] w-[46px] shrink-0 items-center rounded-rack transition-colors',
        nextProps.value ? 'bg-signal-accent' : 'bg-ink-primary/[0.14]',
      )
      thumb.className = classes(
        'absolute top-[3px] h-[19px] w-[19px] rounded-rack transition-[left,background-color]',
        nextProps.value ? 'left-[24px] bg-ink-on-accent' : 'left-[3px] bg-ground-panel',
      )

      if (checkbox.checked !== nextProps.value) {
        checkbox.checked = nextProps.value
      }
      checkbox.disabled = nextProps.disabled ?? false
      setAttribute(checkbox, 'aria-label', nextProps.accessibleName ?? nextProps.label)
    },

    destroy(): void {
      // Only the change listener is attached, and it lives on `checkbox`
      // itself — it is torn down automatically when the node is removed.
    },
  }
}
