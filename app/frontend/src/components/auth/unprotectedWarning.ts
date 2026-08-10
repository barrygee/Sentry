import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import {
  consoleAuthStore,
  shouldWarnUnprotected,
  type ConsoleAuthState,
} from '../../state/consoleAuth.js'
import { baseButton } from '../base/baseButton.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * Standing warning that this console has no password (ADR-0010).
 *
 * Appears once the setup prompt has been declined and stays for the rest of the
 * visit. `role="status"` rather than `alert`: it is a condition the operator has
 * just been asked about and knowingly declined, so interrupting a screen reader
 * with it would be arguing rather than informing.
 *
 * `warn` rather than `danger`. An open console on a home LAN is a defensible
 * choice, and this is a standing state rather than something that went wrong —
 * red would be crying wolf on every page view until it stopped being read.
 */
export interface UnprotectedWarningProps {
  /**
   * What "Set a password" does.
   *
   * Injected rather than fixed here because this component sits in the devices
   * view and the password field lives in Settings — it cannot reach the field
   * itself, and hard-coding navigation into a notice would tie a warning to a
   * layout.
   */
  onSetPassword: () => void
}

export function unprotectedWarning(props: UnprotectedWarningProps): Component<void> {
  const setPasswordButton = baseButton({
    variant: 'on-bright',
    onClick: () => props.onSetPassword(),
    children: ['Set a password'],
  })

  const message = el('p', { class: 'm-0' }, [
    'This Sentry controller has no password — anyone who can reach it can change your SDR settings.',
  ])

  const notice = noticeBox({
    tone: 'warn',
    role: 'status',
    children: [
      el(
        'div',
        { class: 'flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4' },
        [message, setPasswordButton.element],
      ),
    ],
  })

  function render(state: Readonly<ConsoleAuthState>): void {
    setVisible(notice.element, shouldWarnUnprotected(state))
  }

  const unsubscribe = watchStore(consoleAuthStore, render)

  return {
    element: notice.element,

    update(): void {
      // Store-driven.
    },

    destroy(): void {
      unsubscribe()
      setPasswordButton.destroy()
      notice.destroy()
    },
  }
}
