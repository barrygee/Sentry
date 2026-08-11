import { el, setAttribute, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { baseButton } from '../base/baseButton.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import {
  PASSPHRASE_MAX_LENGTH,
  validatePassphraseClientSide,
} from '../../utils/hotspotValidation.js'

/**
 * The hotspot password field, and the "leave it unchanged" affordance that
 * makes the write-only passphrase workable.
 *
 * The server never returns a stored password, so there is nothing to prefill.
 * Rather than presenting an empty box that would silently clear the key (or
 * demand it be retyped on every unrelated edit), a configured hotspot shows
 * *"A password is set"* plus an explicit **Change password** control. Not
 * re-asking for something unchanged is WCAG 3.3.7 Redundant Entry, not merely
 * a convenience — and it is what keeps `passphrase` absent from the request
 * body, which is the signal the API uses.
 *
 * The reveal toggle shows what the operator has just typed, never what the
 * server holds. That is the accessible form of "show password" (WCAG 3.3.8):
 * it helps someone check a long key they entered without ever turning a
 * stored secret into a readable one.
 *
 * Both branches (changing / not-changing) stay mounted for this component's
 * whole lifetime, toggled with `setVisible` rather than swapped in and out —
 * consistent with "never rebuild the subtree" (the field inside holds a
 * secret being typed).
 */
export interface HotspotPassphraseFieldProps {
  /** The passphrase as currently typed. Never populated from the server. */
  value: string
  onChange: (value: string) => void
  /** Whether the server reports a stored password for this hotspot. */
  passphraseSet: boolean
  /** A server-side error for this field, rendered in the same slot as the local one. */
  serverError?: string | null
  disabled?: boolean
  /** Fires whenever the field enters or leaves "changing" mode. */
  onChangingUpdate: (changing: boolean) => void
}

const LABEL_CLASSES =
  'mb-1.5 block select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary'

/** Mirrors the SSID field's counter, reading the validator's own bound. */
function passphraseHint(value: string): string {
  return `${value.length} of ${PASSPHRASE_MAX_LENGTH} characters used.`
}

/** Builds a `HotspotPassphraseField`. `update` mutates the same field in place. */
export function hotspotPassphraseField(
  props: HotspotPassphraseFieldProps,
): Component<HotspotPassphraseFieldProps> {
  let currentProps = props
  // A configured hotspot starts in "keep the existing password" mode; a
  // brand-new one has nothing to keep, so the field is open from the outset.
  let changing = !props.passphraseSet
  let revealed = false
  let touched = false

  const descriptionId = nextElementId('hotspot-passphrase-description')

  function localError(): string | null {
    if (!changing || !touched || currentProps.value === '') {
      return null
    }
    return validatePassphraseClientSide(currentProps.value)
  }

  function fieldError(): string | null {
    return currentProps.serverError ?? localError()
  }

  const revealButton = baseButton({
    variant: 'quiet',
    ariaLabel: 'Show password',
    disabled: props.disabled ?? false,
    onClick: () => {
      revealed = !revealed
      render()
    },
    children: ['Show'],
  })

  const passphraseField = baseField({
    label: 'Password',
    value: props.value,
    onChange: (value) => currentProps.onChange(value),
    type: 'password',
    error: fieldError(),
    hint: fieldError() ? null : passphraseHint(currentProps.value),
    disabled: props.disabled ?? false,
    autocomplete: 'new-password',
    describedBy: props.passphraseSet ? descriptionId : null,
    onBlur: () => {
      touched = true
      render()
    },
    trailingAction: revealButton.element,
  })

  const keepCurrentButton = baseButton({
    variant: 'quiet',
    disabled: props.disabled ?? false,
    onClick: () => keepExisting(),
    children: ['Keep current password'],
  })

  const descriptionParagraph = el(
    'p',
    { attrs: { id: descriptionId }, class: 'text-[11px] leading-[1.6] text-signal-muted' },
    [keepCurrentButton.element],
  )

  const changingBranch = el('div', { class: 'flex flex-col gap-2' }, [
    passphraseField.element,
    descriptionParagraph,
  ])

  const notSetLabel = el('span', { class: LABEL_CLASSES }, ['Password'])

  // Three overrides, each earning its `!`:
  //
  // `min-h` — `BaseButton` floors every button at 38-44px for a comfortable tap
  // target, which centred this row's text below the SSID input beside it. 24px
  // is still WCAG 2.2 AA's minimum target size (2.5.8); it gives up the
  // AAA-sized target (2.5.5), not an AA conformance.
  //
  // `px` — the `quiet` variant already declares `px-0`, and it does not take
  // effect: `BASE_CLASSES` also sets `px-[18px]`, at equal specificity, and wins
  // on stylesheet order. That phantom padding was most of the gap between this
  // button and the text beside it. Fixed here rather than in the variant,
  // because the variant is shared and correcting it silently reflows every other
  // quiet button in the app.
  //
  // `font-normal` — `quiet` is 700; this reads as a link beside a sentence.
  const CHANGE_BUTTON_CLASS = '!min-h-[24px] !px-0 !font-normal leading-[24px]'

  const changeButton = baseButton({
    variant: 'quiet',
    disabled: props.disabled ?? false,
    onClick: () => beginChanging(),
    children: ['Change password'],
    extraClass: CHANGE_BUTTON_CLASS,
  })

  const notChangingRow = el('div', { class: 'flex flex-wrap items-center gap-2' }, [
    el(
      'span',
      { class: 'font-tabular text-[12.5px] leading-[24px] tracking-readout text-ink-primary' },
      ['A password is set'],
    ),
    changeButton.element,
  ])
  // No `gap` here: `notSetLabel` already carries `mb-1.5`, and a gap on top of
  // it stacked 6px + 8px against `BaseField`'s 6px alone, dropping this column
  // 8px below the SSID field beside it.
  const notChangingBranch = el('div', { class: 'flex flex-col' }, [notSetLabel, notChangingRow])

  const root = el('div', { class: 'flex flex-col gap-2' }, [changingBranch, notChangingBranch])

  function beginChanging(): void {
    changing = true
    touched = false
    currentProps.onChange('')
    currentProps.onChangingUpdate(true)
    render()
  }

  function keepExisting(): void {
    changing = false
    revealed = false
    touched = false
    currentProps.onChange('')
    currentProps.onChangingUpdate(false)
    render()
  }

  function render(): void {
    setVisible(changingBranch, changing)
    setVisible(notChangingBranch, !changing)
    setVisible(descriptionParagraph, currentProps.passphraseSet)

    passphraseField.update({
      label: 'Password',
      value: currentProps.value,
      onChange: (value) => currentProps.onChange(value),
      type: revealed ? 'text' : 'password',
      error: fieldError(),
      hint: fieldError() ? null : passphraseHint(currentProps.value),
      disabled: currentProps.disabled ?? false,
      autocomplete: 'new-password',
      describedBy: currentProps.passphraseSet ? descriptionId : null,
      onBlur: () => {
        touched = true
        render()
      },
      trailingAction: revealButton.element,
    })

    revealButton.update({
      variant: 'quiet',
      ariaLabel: revealed ? 'Hide password' : 'Show password',
      disabled: currentProps.disabled ?? false,
      onClick: () => {
        revealed = !revealed
        render()
      },
      children: [revealed ? 'Hide' : 'Show'],
    })
    // `aria-pressed` conveys the reveal toggle's own state, not only its text.
    setAttribute(revealButton.element, 'aria-pressed', revealed ? 'true' : 'false')

    keepCurrentButton.update({
      variant: 'quiet',
      disabled: currentProps.disabled ?? false,
      onClick: () => keepExisting(),
      children: ['Keep current password'],
    })
    changeButton.update({
      variant: 'quiet',
      extraClass: CHANGE_BUTTON_CLASS,
      disabled: currentProps.disabled ?? false,
      onClick: () => beginChanging(),
      children: ['Change password'],
    })
  }

  render()

  return {
    element: root,

    update(nextProps): void {
      currentProps = nextProps
      render()
    },

    destroy(): void {
      passphraseField.destroy()
      revealButton.destroy()
      keepCurrentButton.destroy()
      changeButton.destroy()
    },
  }
}
