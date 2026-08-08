import { classes, el, setAttribute, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { nextElementId } from './idGenerator.js'

/**
 * The single labelled-select primitive, matching `BaseField`'s stacked-field
 * geometry so a select and a text input sitting in the same form align on
 * their label and their text rather than merely on their box.
 *
 * A **native `<select>`**, deliberately, not a custom listbox. A native control
 * is keyboard-operable, screen-reader-correct, and usable with a phone's native
 * picker for free; a hand-rolled listbox would have to re-earn all three and
 * would almost certainly get typeahead, `aria-activedescendant` and touch
 * behaviour subtly wrong. The only thing it costs is control over the option
 * list's appearance, which is worth nothing here.
 *
 * Label/error/hint wiring is identical to `BaseField` — a real `<label for>`, an
 * error associated through `aria-describedby` and announced via `role="alert"`,
 * and `aria-invalid` while one is present — so the two are interchangeable to
 * assistive tech.
 */
export interface BaseSelectOption {
  value: string
  label: string
}

export interface BaseSelectProps {
  label: string
  value: string
  onChange: (value: string) => void
  /** The choices, in display order. `value` is what the selected `value` carries. */
  options: readonly BaseSelectOption[]
  error?: string | null
  hint?: string | null
  disabled?: boolean
  /** Extra id(s) to merge into `aria-describedby`, for content rendered outside this component. */
  describedBy?: string | null
}

export interface BaseSelectHandle extends Component<BaseSelectProps> {
  /** Moves focus into the `<select>`. */
  focus(): void
}

const SELECT_CLASSES =
  'min-h-[24px] w-full min-w-0 appearance-none rounded-rack border-none bg-transparent px-0 py-0 font-tabular text-[12.5px] font-normal leading-[24px] tracking-readout text-ink-primary outline-none transition-shadow shadow-[inset_0_-1px_0_theme(colors.ground.hairline)] focus:shadow-[inset_0_-2px_0_theme(colors.signal.accent)] disabled:cursor-not-allowed disabled:opacity-40'

function resolveDescribedBy(
  hintId: string,
  errorId: string,
  props: Pick<BaseSelectProps, 'hint' | 'error' | 'describedBy'>,
): string | undefined {
  const ids = [
    props.hint ? hintId : null,
    props.error ? errorId : null,
    props.describedBy ?? null,
  ].filter((id): id is string => id !== null)
  return ids.length > 0 ? ids.join(' ') : undefined
}

function buildOption(option: BaseSelectOption): HTMLOptionElement {
  // The option list is the browser's own, so it needs its own background: a
  // transparent option inherits the page's black and renders as
  // black-on-black in the native dropdown on several platforms.
  return el(
    'option',
    { attrs: { value: option.value }, class: 'bg-ground-panel text-ink-primary' },
    [option.label],
  )
}

function optionsMatch(
  previous: readonly BaseSelectOption[],
  next: readonly BaseSelectOption[],
): boolean {
  return (
    previous.length === next.length &&
    previous.every(
      (option, index) => option.value === next[index]?.value && option.label === next[index]?.label,
    )
  )
}

/** Builds a `BaseSelect`. `update` mutates the same `<select>` in place. */
export function baseSelect(props: BaseSelectProps): BaseSelectHandle {
  let currentProps = props
  let currentOptions = props.options
  const fieldId = nextElementId('select')
  const errorId = `${fieldId}-error`
  const hintId = `${fieldId}-hint`

  const label = el(
    'label',
    {
      attrs: { for: fieldId },
      class:
        'mb-1.5 block select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary',
    },
    [props.label],
  )

  const select = el(
    'select',
    {
      attrs: { id: fieldId, disabled: props.disabled ?? false },
      class: classes(
        SELECT_CLASSES,
        props.error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
      ),
      on: {
        change: () => currentProps.onChange(select.value),
      },
    },
    props.options.map(buildOption),
  )
  select.value = props.value

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

  const root = el('div', { class: 'flex flex-col' }, [label, select, hintParagraph, errorParagraph])

  function applyDescribedBy(selectProps: BaseSelectProps): void {
    setAttribute(
      select,
      'aria-describedby',
      resolveDescribedBy(hintId, errorId, selectProps) ?? null,
    )
    setAttribute(select, 'aria-invalid', selectProps.error ? 'true' : null)
  }

  function applyHintAndError(selectProps: BaseSelectProps): void {
    const showHint = Boolean(selectProps.hint) && !selectProps.error
    setVisible(hintParagraph, showHint)
    setText(hintParagraph, showHint ? (selectProps.hint ?? '') : '')

    const showError = Boolean(selectProps.error)
    setVisible(errorParagraph, showError)
    setText(errorParagraph, showError ? (selectProps.error ?? '') : '')
  }

  applyDescribedBy(props)
  applyHintAndError(props)

  return {
    element: root,

    focus(): void {
      select.focus()
    },

    update(nextProps): void {
      currentProps = nextProps

      setText(label, nextProps.label)

      if (!optionsMatch(currentOptions, nextProps.options)) {
        select.replaceChildren(...nextProps.options.map(buildOption))
        currentOptions = nextProps.options
      }

      if (select.value !== nextProps.value) {
        select.value = nextProps.value
      }
      select.disabled = nextProps.disabled ?? false
      select.className = classes(
        SELECT_CLASSES,
        nextProps.error ? 'shadow-[inset_0_-2px_0_theme(colors.signal.danger)]' : '',
      )

      applyDescribedBy(nextProps)
      applyHintAndError(nextProps)
    },

    destroy(): void {
      // Only the change listener is attached, and it lives on `select`
      // itself — it is torn down automatically when the node is removed.
    },
  }
}
