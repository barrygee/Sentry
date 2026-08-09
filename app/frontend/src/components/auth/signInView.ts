import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import {
  consoleAuthStore,
  mustSignIn,
  signIn,
  type ConsoleAuthState,
} from '../../state/consoleAuth.js'
import { baseButton } from '../base/baseButton.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'

/**
 * The sign-in screen, shown in place of the whole console when a password is
 * set and this browser has no valid session (ADR-0010).
 *
 * Not a dialog. A dialog implies something behind it that you could return to,
 * and there is nothing to return to — every management route answers 401 until
 * this is satisfied. It is also the reason there is no dismiss control: the
 * only way past it is to sign in.
 *
 * Replaces `authTokenPrompt`, which asked for a 64-character hex string an
 * operator had to have copied from a terminal.
 */
export function signInView(): Component<void> {
  const headingId = nextElementId('sign-in-heading')

  let draftPassword = ''

  const heading = sectionHeading({ level: 1, children: ['Sign in'] })
  heading.element.id = headingId
  heading.element.setAttribute('tabindex', '-1')

  const introParagraph = el('p', { class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' }, [
    'This Sentry controller is protected by a password. Enter it to manage the SDRs.',
  ])

  const passwordField = baseField({
    label: 'Password',
    value: '',
    type: 'password',
    onChange: (value) => {
      draftPassword = value
    },
  })

  const errorNotice = noticeBox({ tone: 'danger', role: 'alert', children: [] })

  const submitButton = baseButton({
    type: 'submit',
    variant: 'primary',
    children: ['Sign in'],
  })

  const form = el(
    'form',
    {
      class: 'flex w-full max-w-[360px] flex-col gap-4',
      attrs: { 'aria-labelledby': headingId },
      on: {
        submit: (event) => {
          event.preventDefault()
          void signIn(draftPassword)
        },
      },
    },
    [
      el('div', { class: 'flex flex-col gap-2' }, [heading.element, introParagraph]),
      errorNotice.element,
      passwordField.element,
      submitButton.element,
    ],
  )

  // Centred on the page ground rather than over a dimmed console: there is no
  // console to dim yet, and showing one behind glass would suggest the data is
  // there and merely obscured.
  const root = el(
    'div',
    { class: 'flex min-h-screen w-full items-center justify-center bg-ground-canvas px-5' },
    [form],
  )

  function render(state: Readonly<ConsoleAuthState>): void {
    const visible = mustSignIn(state)
    setVisible(root, visible)
    if (!visible) return

    const busy = state.phase === 'submitting'
    submitButton.update({
      type: 'submit',
      variant: 'primary',
      disabled: busy,
      children: [busy ? 'Signing in…' : 'Sign in'],
    })

    setVisible(errorNotice.element, state.errorMessage !== null)
    if (state.errorMessage !== null) {
      errorNotice.update({ tone: 'danger', role: 'alert', children: [state.errorMessage] })
    }
  }

  const unsubscribe = watchStore(consoleAuthStore, render)

  return {
    element: root,

    update(): void {
      // Store-driven.
    },

    destroy(): void {
      unsubscribe()
      passwordField.destroy()
      submitButton.destroy()
      errorNotice.destroy()
      heading.destroy()
    },
  }
}
