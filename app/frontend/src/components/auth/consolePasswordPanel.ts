import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import { consoleAuthStore, setPassword, type ConsoleAuthState } from '../../state/consoleAuth.js'
import { baseButton } from '../base/baseButton.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { sectionHeading } from '../base/sectionHeading.js'

/**
 * The Settings section for the console password (ADR-0010).
 *
 * Handles both jobs the same form can: setting the first password on an open
 * console, and changing an existing one. The current-password field appears
 * only in the second case — there is no secret to prove knowledge of in the
 * first, and asking for one would make an open console impossible to protect.
 */
/** A `ConsolePasswordPanel`, which additionally lets a caller focus its password box. */
export type ConsolePasswordPanel = Component<void> & { focusPasswordField: () => void }

export function consolePasswordPanel(): ConsolePasswordPanel {
  const headingId = nextElementId('console-password-heading')

  let draftCurrent = ''
  let draftNew = ''

  const heading = sectionHeading({
    level: 2,
    size: 'item',
    children: ['Sentry controller password'],
  })
  heading.element.id = headingId

  const introParagraph = el(
    'p',
    { class: 'm-0 text-[12.5px] leading-[1.55] text-signal-muted' },
    [],
  )

  const statusLine = el('p', { class: 'm-0 text-[12px] text-signal-muted' }, [])

  const currentField = baseField({
    label: 'Current password',
    value: '',
    type: 'password',
    onChange: (value) => {
      draftCurrent = value
    },
  })

  const newField = baseField({
    label: 'New password',
    value: '',
    type: 'password',
    onChange: (value) => {
      draftNew = value
    },
  })

  const errorNotice = noticeBox({ tone: 'danger', role: 'alert', children: [] })
  const successNotice = noticeBox({
    tone: 'ok',
    role: 'status',
    children: ['Password updated. Any other signed-in browser has been signed out.'],
  })

  const saveButton = baseButton({
    type: 'submit',
    variant: 'on-bright',
    children: ['Set password'],
  })
  const form = el(
    'form',
    {
      class: 'flex flex-col gap-4',
      on: {
        submit: (event) => {
          event.preventDefault()
          const current = consoleAuthStore.state.passwordSet ? draftCurrent : null
          void setPassword(draftNew, current).then((succeeded) => {
            if (succeeded) {
              draftCurrent = ''
              draftNew = ''
              showSuccess = true
              // Re-render through the store so the cleared fields and the
              // confirmation land in the same paint.
              consoleAuthStore.setState({ errorMessage: null })
            }
          })
        },
      },
    },
    [
      currentField.element,
      newField.element,
      // Wrapped, not bare: a direct child of a `flex-col` stretches to the
      // container's width, which made this the only full-width button in the
      // app. The hotspot form's action row solves it the same way.
      el('div', { class: 'flex flex-wrap items-center gap-2' }, [saveButton.element]),
    ],
  )

  const root = el(
    'section',
    {
      class: 'flex flex-col gap-4 bg-ground-panel p-card',
      attrs: { 'aria-labelledby': headingId },
    },
    [
      el('div', { class: 'flex flex-col gap-2' }, [heading.element, introParagraph, statusLine]),
      errorNotice.element,
      successNotice.element,
      form,
      // A `flex` row, hidden as a whole rather than `contents` with the button
      // hidden inside. `contents` promoted the button to a flex item of the
      // column, which stretched it to full width; hiding the wrapper keeps the
      // button its own size and still contributes no gap when it is away.
    ],
  )

  let showSuccess = false

  function render(state: Readonly<ConsoleAuthState>): void {
    const busy = state.phase === 'submitting'

    setText(
      introParagraph,
      state.passwordSet
        ? 'Changing the password signs out every other browser immediately, including one you no longer have.'
        : 'This Sentry controller has no password. Anyone who can reach it can change your SDR settings.',
    )
    setText(
      statusLine,
      state.passwordSet && state.updatedAt > 0
        ? `Last changed ${new Date(state.updatedAt).toLocaleString()}.`
        : '',
    )
    setVisible(statusLine, state.passwordSet && state.updatedAt > 0)

    // Only meaningful when there is a password to prove knowledge of.
    setVisible(currentField.element, state.passwordSet)
    // Signing out of a console with no password would strand the operator on a
    // sign-in screen with nothing to sign in to.

    newField.update({
      label: 'New password',
      value: '',
      type: 'password',
      hint: `At least ${state.minimumPasswordLength} characters.`,
      disabled: busy,
      onChange: (value) => {
        draftNew = value
      },
    })
    currentField.update({
      label: 'Current password',
      value: '',
      type: 'password',
      disabled: busy,
      onChange: (value) => {
        draftCurrent = value
      },
    })
    saveButton.update({
      type: 'submit',
      variant: 'on-bright',
      disabled: busy,
      children: [busy ? 'Saving…' : 'Save password'],
    })

    setVisible(errorNotice.element, state.errorMessage !== null)
    if (state.errorMessage !== null) {
      errorNotice.update({ tone: 'danger', role: 'alert', children: [state.errorMessage] })
      showSuccess = false
    }
    setVisible(successNotice.element, showSuccess && state.errorMessage === null)
  }

  const unsubscribe = watchStore(consoleAuthStore, render)

  return {
    element: root,

    /**
     * Put the caret in the password box.
     *
     * Called when the operator arrives from the "no password set" warning in
     * the devices view: they asked to set a password, so landing them on the
     * settings page and making them find the field again would be answering a
     * different question than the one the button asked.
     */
    focusPasswordField(): void {
      newField.focus()
    },

    update(): void {
      // Store-driven.
    },

    destroy(): void {
      unsubscribe()
      currentField.destroy()
      newField.destroy()
      saveButton.destroy()
      errorNotice.destroy()
      successNotice.destroy()
      heading.destroy()
    },
  }
}
