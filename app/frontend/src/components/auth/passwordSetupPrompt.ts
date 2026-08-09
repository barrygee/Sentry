import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import {
  consoleAuthStore,
  declineSetupPrompt,
  setPassword,
  type ConsoleAuthState,
} from '../../state/consoleAuth.js'
import { baseButton } from '../base/baseButton.js'
import { baseDialog } from '../base/baseDialog.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'

/**
 * Asks an unprotected console's operator to set a password (ADR-0010).
 *
 * Raised once per visit while no password exists, and declinable — the console
 * stays open if that is what the operator wants, which is the documented
 * default rather than a state to be nagged out of. Declining does not end the
 * matter, though: the warning banner takes its place, and the prompt returns
 * next visit. An open console is a standing condition, not a one-off notice, so
 * a "don't show again" would be the UI helping someone forget.
 *
 * Dismissible by `Escape` like any other dialog. There is nothing dangerous
 * behind it and nothing in flight — refusing to close would be theatre.
 */
export function passwordSetupPrompt(): Component<void> {
  const headingId = nextElementId('password-setup-heading')

  let draftPassword = ''

  const heading = sectionHeading({ level: 2, children: ['Set a Sentry controller password'] })
  heading.element.id = headingId

  const introParagraph = el('p', { class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' }, [
    'Anyone who can reach this Sentry can currently rename your SDRs, change their ports, ' +
      'disable them, or export your whole configuration. A password stops that.',
  ])

  const listeningParagraph = el(
    'p',
    { class: 'm-0 text-[12px] leading-[1.55] text-signal-muted' },
    [
      'Listening is unaffected either way — SDR clients connect straight to the dongle ports ' +
        'and never see this controller.',
    ],
  )

  const passwordField = baseField({
    label: 'New password',
    value: '',
    type: 'password',
    hint: 'At least 8 characters. Choose something long rather than complicated.',
    onChange: (value) => {
      draftPassword = value
    },
  })

  const errorNotice = noticeBox({ tone: 'danger', role: 'alert', children: [] })

  const saveButton = baseButton({ type: 'submit', variant: 'primary', children: ['Set password'] })
  const laterButton = baseButton({
    variant: 'ghost',
    onClick: () => declineSetupPrompt(),
    children: ['Not now'],
  })

  const form = el(
    'form',
    {
      class: 'flex flex-col gap-4',
      on: {
        submit: (event) => {
          event.preventDefault()
          void setPassword(draftPassword, null)
        },
      },
    },
    [
      el('div', { class: 'flex flex-col gap-2' }, [
        heading.element,
        introParagraph,
        listeningParagraph,
      ]),
      errorNotice.element,
      passwordField.element,
      el('div', { class: 'flex flex-wrap items-center gap-2' }, [
        saveButton.element,
        laterButton.element,
      ]),
    ],
  )

  const dialog = baseDialog({
    open: false,
    labelledBy: headingId,
    disableDismiss: false,
    onClose: () => declineSetupPrompt(),
    children: [form],
  })

  function render(state: Readonly<ConsoleAuthState>): void {
    const busy = state.phase === 'submitting'

    saveButton.update({
      type: 'submit',
      variant: 'primary',
      disabled: busy,
      children: [busy ? 'Setting…' : 'Set password'],
    })
    laterButton.update({
      variant: 'ghost',
      disabled: busy,
      onClick: () => declineSetupPrompt(),
      children: ['Not now'],
    })
    passwordField.update({
      label: 'New password',
      value: '',
      type: 'password',
      hint: `At least ${state.minimumPasswordLength} characters. Choose something long rather than complicated.`,
      onChange: (value) => {
        draftPassword = value
      },
    })

    setVisible(errorNotice.element, state.errorMessage !== null)
    if (state.errorMessage !== null) {
      errorNotice.update({ tone: 'danger', role: 'alert', children: [state.errorMessage] })
    }

    dialog.update({
      open: state.setupPromptOpen,
      labelledBy: headingId,
      disableDismiss: busy,
      onClose: () => declineSetupPrompt(),
      children: [form],
    })
  }

  const unsubscribe = watchStore(consoleAuthStore, render)

  return {
    element: dialog.element,

    update(): void {
      // Store-driven.
    },

    destroy(): void {
      unsubscribe()
      passwordField.destroy()
      saveButton.destroy()
      laterButton.destroy()
      errorNotice.destroy()
      heading.destroy()
      dialog.destroy()
    },
  }
}
