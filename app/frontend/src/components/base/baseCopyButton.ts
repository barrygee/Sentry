import { classes, el, setText } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { baseButton } from './baseButton.js'

/**
 * Copies a short value to the clipboard and says so.
 *
 * Exists because the hotspot's gateway address is a value an operator has to
 * retype by hand into a *different application* on a *different machine* — the
 * one case in this app where getting a string out accurately matters more than
 * reading it.
 *
 * The confirmation is announced through a `role="status"` region that is
 * present from mount rather than created on click: a live region inserted into
 * the DOM already containing its text is frequently not announced at all, the
 * same trap `SerialFlashDialog` documents. Only the text changes.
 *
 * Failure is surfaced, not swallowed. `navigator.clipboard` rejects on an
 * insecure origin — which is precisely where Sentry lives, plain HTTP on a LAN
 * — so silently doing nothing would be the common case, not the rare one.
 */
export interface BaseCopyButtonProps {
  /** The text to place on the clipboard. */
  value: string
  /** Accessible name; should name what is being copied, not just "Copy". */
  accessibleName: string
  label?: string
}

type CopyOutcome = 'idle' | 'copied' | 'failed'

const RESET_DELAY_MS = 2500

/** Builds a `BaseCopyButton`. `update` mutates its wrapper in place. */
export function baseCopyButton(props: BaseCopyButtonProps): Component<BaseCopyButtonProps> {
  let currentProps = props
  let outcome: CopyOutcome = 'idle'
  let resetTimer: ReturnType<typeof setTimeout> | undefined

  const outcomeRegion = el('span', {
    attrs: { role: 'status' },
    class: classes('text-[11px]', 'text-signal-muted'),
  })

  const button = baseButton({
    variant: 'ghost',
    ariaLabel: props.accessibleName,
    onClick: () => void copy(),
    children: [props.label ?? 'Copy'],
  })

  const wrapper = el('span', { class: 'inline-flex items-center gap-2' }, [
    button.element,
    outcomeRegion,
  ])

  function renderOutcome(): void {
    outcomeRegion.className = classes(
      'text-[11px]',
      outcome === 'failed' ? 'text-signal-warn' : 'text-signal-muted',
    )
    setText(
      outcomeRegion,
      outcome === 'copied' ? 'Copied' : outcome === 'failed' ? 'Copy it manually' : '',
    )
  }

  async function copy(): Promise<void> {
    clearTimeout(resetTimer)
    try {
      await navigator.clipboard.writeText(currentProps.value)
      outcome = 'copied'
    } catch {
      // Most likely an insecure origin or a denied permission. Either way the
      // operator needs to know to select the text themselves.
      outcome = 'failed'
    }
    renderOutcome()
    resetTimer = setTimeout(() => {
      outcome = 'idle'
      renderOutcome()
    }, RESET_DELAY_MS)
  }

  return {
    element: wrapper,

    update(nextProps): void {
      currentProps = nextProps
      button.update({
        variant: 'ghost',
        ariaLabel: nextProps.accessibleName,
        onClick: () => void copy(),
        children: [nextProps.label ?? 'Copy'],
      })
    },

    destroy(): void {
      clearTimeout(resetTimer)
      button.destroy()
    },
  }
}
