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
 * same trap `SerialFlashSection` documents. Only the text changes.
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

  /**
   * The pre-`navigator.clipboard` route: select a detached textarea and copy.
   *
   * Deprecated, and load-bearing here. `navigator.clipboard` exists only in a
   * secure context, and Sentry's normal deployment is not one — it is served
   * over plain HTTP at `http://<PI_IP>:8000`. The modern API is therefore
   * `undefined` for every real operator, and present only on `localhost`, which
   * is exactly where anyone testing this would be. The button reported "Copy it
   * manually" on every Pi in the world and worked perfectly on the developer's
   * machine.
   *
   * Must run inside the click's user activation, which is why availability is
   * checked synchronously below rather than after an `await`.
   */
  function copyBySelection(value: string): boolean {
    const scratch = document.createElement('textarea')
    scratch.value = value
    scratch.setAttribute('readonly', '')
    // Off-screen rather than hidden: `display:none` or `hidden` cannot be
    // selected, and an unselected textarea copies nothing.
    scratch.style.position = 'fixed'
    scratch.style.top = '-9999px'
    scratch.style.opacity = '0'
    document.body.appendChild(scratch)

    const previouslyFocused = document.activeElement
    scratch.select()

    let succeeded = false
    try {
      succeeded = document.execCommand('copy')
    } catch {
      succeeded = false
    }

    scratch.remove()
    // Selecting the scratch element took focus; put it back rather than
    // dropping a keyboard user onto `<body>`.
    if (previouslyFocused instanceof HTMLElement) {
      previouslyFocused.focus()
    }
    return succeeded
  }

  async function copy(): Promise<void> {
    clearTimeout(resetTimer)

    // Checked synchronously: `await` would end the user activation that
    // `execCommand` needs, so the fallback has to be reachable without one.
    if (typeof navigator.clipboard?.writeText !== 'function') {
      outcome = copyBySelection(currentProps.value) ? 'copied' : 'failed'
      renderOutcome()
      resetTimer = setTimeout(() => {
        outcome = 'idle'
        renderOutcome()
      }, RESET_DELAY_MS)
      return
    }

    try {
      await navigator.clipboard.writeText(currentProps.value)
      outcome = 'copied'
    } catch {
      // Present but refused — a denied permission, or a browser that rejects
      // the write from this context. Worth one attempt at the old route.
      outcome = copyBySelection(currentProps.value) ? 'copied' : 'failed'
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
