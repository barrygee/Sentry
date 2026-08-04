import { el } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import { baseButton } from '../base/baseButton.js'
import { baseDialog } from '../base/baseDialog.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { sectionHeading } from '../base/sectionHeading.js'
import {
  authTokenStore,
  dismissAuthPrompt,
  setAuthToken,
  type AuthTokenState,
} from '../../state/authToken.js'

/**
 * Operator-facing prompt for `SENTRY_AUTH_TOKEN` (architecture §7.9) —
 * rendered once near the app root and driven entirely by
 * `authTokenStore.promptRequired`, which `api/client.ts` sets the moment any
 * request comes back `401`. Without this the console has no in-app way to
 * supply a token: every fetch and the SSE stream would 401 forever.
 *
 * Takes no props.
 */
export function authTokenPrompt(): Component<void> {
  const headingId = nextElementId('auth-token-prompt-heading')

  let draft = ''

  const heading = sectionHeading({ level: 2, children: ['Authentication required'] })
  heading.element.id = headingId
  const introParagraph = el('p', { class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' }, [
    'This Sentry instance requires an operator token. Enter the value configured as ',
    el('code', { class: 'font-mono' }, ['SENTRY_AUTH_TOKEN']),
    ' to continue — it is kept only for this browser tab.',
  ])
  const headerBlock = el('div', { class: 'flex flex-col gap-2' }, [heading.element, introParagraph])

  const tokenField = baseField({
    label: 'Access token',
    value: '',
    onChange: (value) => {
      draft = value
    },
  })

  const connectButton = baseButton({
    type: 'submit',
    variant: 'primary',
    children: ['Connect'],
  })
  const actionsRow = el('div', { class: 'flex justify-end gap-2' }, [connectButton.element])

  const form = el(
    'form',
    {
      class: 'flex flex-col gap-3',
      on: {
        submit: (event) => {
          event.preventDefault()
          submit()
        },
      },
    },
    [tokenField.element, actionsRow],
  )

  const dialog = baseDialog({
    open: false,
    labelledBy: headingId,
    onClose: () => dismissAuthPrompt(),
    children: [headerBlock, form],
  })

  function submit(): void {
    if (draft.trim().length === 0) {
      return
    }
    setAuthToken(draft)
    draft = ''
    tokenField.update({
      label: 'Access token',
      value: draft,
      onChange: (value) => {
        draft = value
      },
    })
  }

  function render(state: AuthTokenState): void {
    dialog.update({
      open: state.promptRequired,
      labelledBy: headingId,
      onClose: () => dismissAuthPrompt(),
      children: [headerBlock, form],
    })
  }

  const unsubscribe = watchStore(authTokenStore, render)

  return {
    element: dialog.element,

    update(): void {
      // Store-driven; nothing to do for a prop this component does not take.
    },

    destroy(): void {
      unsubscribe()
      dialog.destroy()
    },
  }
}
