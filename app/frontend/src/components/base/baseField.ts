import { classes, el, setAttribute, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { nextElementId } from './idGenerator.js'

/**
 * The single labelled-text-entry primitive — an `<input>`, or a `<textarea>`
 * when `multiline`: a real `<label for>`, an inline error associated via
 * `aria-describedby`, and `aria-invalid` set whenever an error is present.
 * Device name, port, antenna, notes fields and any future form field compose
 * this rather than re-implementing label/error wiring (architecture §9.4
 * forms rule).
 *
 * Visually it is Sentinel's stacked field, near its settings-card scale: an
 * 11px uppercase label above its own flat, square input
 * whose text is the 12.5px `.settings-item-desc` size, with the accent
 * underline drawn inside the input on focus and a red one while invalid.
 *
 * The input has no fill of its own and no padding, so it reads as a value on
 * the card rather than a box sitting on it, and its text starts on the same
 * vertical line as the label above. Its weight matches the read-only values it
 * sits beside, so an editable field and a fixed one differ only by being
 * editable.
 *
 * Its 6px label gap and 24px line box are shared with `DataCell` — that pairing
 * is what lets a field and a readout on the same row align on their text rather
 * than merely starting at the same height, so the two must always be changed
 * together. 24px is also the WCAG 2.2 AA target minimum, which the old 40px box
 * cleared comfortably and this one only meets.
 *
 * One deliberate difference — Sentinel uppercases its search text, which
 * suits a filter keyword but would misrepresent a device name the operator
 * typed, so the value keeps its own casing here.
 *
 * Exposes `focus()` so a caller whose blur-triggered validation just failed
 * can return focus to the input — otherwise a commit-on-blur error leaves
 * focus wherever the operator tabbed to next, and a screen-reader user never
 * hears which field it was about.
 *
 * `multiline` and the resulting `<input>`/`<textarea>` choice is read once at
 * construction, matching how every caller actually uses this component — a
 * field's shape does not change after mount — which keeps the single DOM
 * node this factory builds honest with "never rebuild the subtree".
 */
export interface BaseFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string | null
  hint?: string | null
  /**
   * The input type. `password` masks the value; the *logic* around a
   * password — a reveal toggle, or "leave blank to keep the stored one" —
   * deliberately lives in the composing field, not here, so this stays the
   * single label/error/aria primitive rather than growing a second job.
   */
  type?: 'text' | 'number' | 'password'
  inputMode?: 'text' | 'numeric'
  disabled?: boolean
  /**
   * Render a `<textarea>` instead of an `<input>`, for free text that runs
   * to more than one line (device notes). Everything else — the `<label
   * for>`, the `aria-describedby` wiring, `aria-invalid`, the focus
   * underline — is identical, which is exactly why this is a flag here
   * rather than a second component duplicating that wiring.
   */
  multiline?: boolean
  /** Visible rows when `multiline`; ignored otherwise. */
  rows?: number
  /** Extra id(s) to merge into `aria-describedby`, for content the caller renders outside this component. */
  describedBy?: string | null
  /**
   * Forwarded to the input's `autocomplete` attribute.
   *
   * Needed for `type="password"`: `new-password` is what lets a password
   * manager offer to generate and store the value (WCAG 3.3.8 Accessible
   * Authentication), and omitting it leaves an operator hand-typing a long
   * random key from memory.
   */
  autocomplete?: string | null
  onBlur?: () => void
  /** Named slot: content placed inside the field's underline, beside the input — e.g. a password reveal toggle. Ignored when `multiline`. */
  trailingAction?: Node | null
}

export interface BaseFieldHandle extends Component<BaseFieldProps> {
  /** Moves focus into the input/textarea. */
  focus(): void
}

// Held in one place rather than repeated across the `<input>` and
// `<textarea>` branches — the two controls are meant to be visually
// indistinguishable apart from height, and two copies of a class string this
// long would not stay that way.
const CONTROL_CLASSES =
  'min-h-[24px] w-full min-w-0 rounded-rack border-none bg-transparent px-0 text-[12.5px] font-normal leading-[24px] font-tabular tracking-readout text-ink-primary caret-ink-primary outline-none shadow-[inset_0_-1px_0_theme(colors.ground.hairline)] transition-shadow focus:shadow-[inset_0_-2px_0_theme(colors.signal.accent)] disabled:cursor-not-allowed disabled:opacity-40'

function resolveDescribedBy(
  hintId: string,
  errorId: string,
  props: Pick<BaseFieldProps, 'hint' | 'error' | 'describedBy'>,
): string | undefined {
  const ids = [
    props.hint ? hintId : null,
    props.error ? errorId : null,
    props.describedBy ?? null,
  ].filter((id): id is string => id !== null)
  return ids.length > 0 ? ids.join(' ') : undefined
}

/** Builds a `BaseField`. `update` mutates the same input/textarea in place — the value is only ever written when it actually differs, so the caret is never disturbed. */
export function baseField(props: BaseFieldProps): BaseFieldHandle {
  let currentProps = props
  const fieldId = nextElementId('field')
  const errorId = `${fieldId}-error`
  const hintId = `${fieldId}-hint`
  const isMultiline = props.multiline ?? false

  const label = el(
    'label',
    {
      attrs: { for: fieldId },
      class:
        'mb-1.5 block select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary',
    },
    [props.label],
  )

  const control = isMultiline
    ? el('textarea', {
        attrs: { id: fieldId, rows: props.rows ?? 3, disabled: props.disabled ?? false },
        class: classes(
          CONTROL_CLASSES,
          'resize-y',
          props.error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
        ),
        on: {
          input: () => currentProps.onChange((control as HTMLTextAreaElement).value),
          blur: () => currentProps.onBlur?.(),
        },
      })
    : el('input', {
        attrs: {
          id: fieldId,
          type: props.type ?? 'text',
          inputmode: props.inputMode ?? 'text',
          disabled: props.disabled ?? false,
          autocomplete: props.autocomplete ?? undefined,
        },
        class: classes(
          CONTROL_CLASSES,
          props.error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
        ),
        on: {
          input: () => currentProps.onChange((control as HTMLInputElement).value),
          blur: () => currentProps.onBlur?.(),
        },
      })

  control.value = props.value

  const hintParagraph = el(
    'p',
    { attrs: { id: hintId }, class: 'mt-2 text-[11px] text-signal-muted' },
    [],
  )
  const errorParagraph = el(
    'p',
    { attrs: { id: errorId, role: 'alert' }, class: 'mt-2 text-[11px] text-signal-danger' },
    [],
  )

  // The trailing action (a password reveal toggle, say) sits inside the
  // field's underline rather than beside the whole control, so the
  // underline still reads as one input. `items-end` keeps a 24px-tall
  // button aligned to the text baseline rather than floating.
  const controlRow = el('div', { class: 'flex items-end gap-2' }, [control])
  if (props.trailingAction) {
    controlRow.appendChild(props.trailingAction)
  }

  const root = el('div', { class: 'flex flex-col' }, [
    label,
    isMultiline ? control : controlRow,
    hintParagraph,
    errorParagraph,
  ])

  function applyDescribedBy(fieldProps: BaseFieldProps): void {
    setAttribute(
      control,
      'aria-describedby',
      resolveDescribedBy(hintId, errorId, fieldProps) ?? null,
    )
    setAttribute(control, 'aria-invalid', fieldProps.error ? 'true' : null)
  }

  function applyHintAndError(fieldProps: BaseFieldProps): void {
    const showHint = Boolean(fieldProps.hint) && !fieldProps.error
    setVisible(hintParagraph, showHint)
    setText(hintParagraph, showHint ? (fieldProps.hint ?? '') : '')

    const showError = Boolean(fieldProps.error)
    setVisible(errorParagraph, showError)
    setText(errorParagraph, showError ? (fieldProps.error ?? '') : '')
  }

  applyDescribedBy(props)
  applyHintAndError(props)

  return {
    element: root,

    focus(): void {
      control.focus()
    },

    update(nextProps): void {
      currentProps = nextProps

      setText(label, nextProps.label)

      // Never while it has focus. Writing `value` on a focused input replaces
      // what is being typed and moves the caret to the end, so a background
      // refresh — `health` arrives every 5 seconds — would eat keystrokes. The
      // caller owning the draft is the one that decides what the value is
      // while an edit is in progress; this is the last line of defence.
      const hasFocus = document.activeElement === control
      if (!hasFocus && control.value !== nextProps.value) {
        control.value = nextProps.value
      }
      control.disabled = nextProps.disabled ?? false

      const errorShadow = nextProps.error
        ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]'
        : ''
      control.className = isMultiline
        ? classes(CONTROL_CLASSES, 'resize-y', errorShadow)
        : classes(CONTROL_CLASSES, errorShadow)

      if (!isMultiline) {
        const inputControl = control as HTMLInputElement
        inputControl.type = nextProps.type ?? 'text'
        setAttribute(inputControl, 'inputmode', nextProps.inputMode ?? 'text')
        setAttribute(inputControl, 'autocomplete', nextProps.autocomplete ?? null)
      } else {
        const textareaControl = control as HTMLTextAreaElement
        textareaControl.rows = nextProps.rows ?? 3
      }

      applyDescribedBy(nextProps)
      applyHintAndError(nextProps)
    },

    destroy(): void {
      // Only listeners on `control` itself, which dies with the node.
    },
  }
}
