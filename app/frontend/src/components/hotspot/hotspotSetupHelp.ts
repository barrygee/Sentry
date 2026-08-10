import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { setControlEnabled } from '../../state/hotspotStore.js'
import { baseToggle } from '../base/baseToggle.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * What is still missing before a hotspot can start, and how to supply it.
 *
 * Two prerequisites, and they are satisfied in different places — which is the
 * whole reason this card exists rather than a form.
 *
 * Hotspot control is now a switch here rather than a line to paste into `.env`
 * (ADR-0013). It used to be deploy-time only, and the reasoning was sound while
 * it held: shell access to the Pi was the thing standing between a stranger and
 * this host's networking (ADR-0007). What replaced it is the controller
 * password — which is why the toggle is *refused*, not merely hidden, until one
 * is set, and why the password prerequisite is stated before the switch rather
 * than after it.
 *
 * The **controller password** is set in the UI, one section above this one. It
 * used to be `SENTRY_AUTH_TOKEN` in the same `.env`, and this card still said
 * so long after ADR-0010 removed it — telling operators to add a line that did
 * nothing.
 */
export interface HotspotSetupHelpProps {
  /** Whether host WiFi control is switched on for this deployment. */
  controlEnabled: boolean
  /**
   * Whether a controller password is set.
   *
   * Named for the wire field it comes from (`auth_token_configured`), which is
   * itself a leftover from the token this replaced — worth renaming, but that
   * is a wire change rather than a copy fix.
   */
  authTokenConfigured: boolean
}

/** Builds a `HotspotSetupHelp`. `update` mutates the same notice in place. */
export function hotspotSetupHelp(props: HotspotSetupHelpProps): Component<HotspotSetupHelpProps> {
  let currentProps = props

  // Two paragraphs rather than one wrapped line: the first states the condition,
  // the second says what to do about it, and they are read at different moments.
  // Running them together left the instruction starting mid-line, where it reads
  // as a continuation of the state rather than an action.
  const introLead = el('p', { class: 'm-0 font-semibold' }, ['Hotspot control is switched off.'])
  const introRest = el('p', { class: 'm-0' }, [])
  const introParagraph = el('div', { class: 'flex flex-col gap-1' }, [introLead, introRest])

  const controlToggle = baseToggle({
    value: false,
    onChange: (enabled) => {
      void setControlEnabled(enabled)
    },
    label: 'Allow hotspot control',
    accessibleName: 'Allow this Sentry to configure the Pi’s WiFi',
  })

  // The switch grants the capability every other hotspot control depends on, so
  // it is disabled — not hidden — until a password exists. Hidden would read as
  // "not available on this Pi"; disabled alongside the reason reads as "do this
  // first", which is what is actually true.
  const controlToggleRow = el('div', { class: 'flex flex-col gap-2' }, [controlToggle.element])

  // The whole control step, hidden once control is enabled. Grouped so intro
  // and switch disappear together rather than leaving an orphan.
  const shellStep = el('div', { class: 'flex flex-col gap-3' }, [])

  shellStep.append(introParagraph, controlToggleRow)

  const wrapper = el('div', { class: 'flex flex-col gap-3' }, [shellStep])

  // Roomier than the default `px-4 py-3`: this is a panel of instructions, not
  // a one-line alert, and at the default its code block and button sat against
  // the fill's edges.
  const SETUP_CARD_PADDING = 'px-6 py-5'

  const notice = noticeBox({
    tone: 'warn',
    role: 'alert',
    extraClasses: SETUP_CARD_PADDING,
    children: [wrapper],
  })

  // Outside the notice on purpose. The box carries the decision — a state and
  // the switch that changes it — and stays short enough to read at a glance.
  // The reasoning belongs on the page, where it explains without competing with
  // the control for attention.
  const controlEnabledParagraph = el(
    'p',
    { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' },
    [
      'Hotspot control is off by default because it is the one setting that lets this web API reconfigure the Pi’s own networking. It stays off until you turn it on, and needs a controller password first.',
    ],
  )
  const passwordParagraph = el('p', { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' }, [
    'A controller password is also required before a hotspot can start: anyone connected to the Sentry WiFi is on the same network as this controller, and could change your SDR settings. Set one in ',
    el('strong', { class: 'font-semibold' }, ['Sentry controller password']),
    ' above.',
  ])

  const root = el('div', { class: 'flex flex-col gap-4' }, [
    notice.element,
    controlEnabledParagraph,
    passwordParagraph,
  ])

  function render(nextProps: HotspotSetupHelpProps): void {
    currentProps = nextProps
    // Each prerequisite shows only while it is unmet. A satisfied one left on
    // screen reads as another thing still to do.
    setVisible(shellStep, !nextProps.controlEnabled)
    setVisible(controlEnabledParagraph, !nextProps.controlEnabled)
    setVisible(passwordParagraph, !nextProps.authTokenConfigured)
    // The one sentence carries the password requirement when there is one,
    // because the toggle below it is disabled in that state and a control that
    // refuses to move without saying why is worse than no control at all.
    setText(
      introRest,
      nextProps.authTokenConfigured
        ? 'Turn it on to let this Sentry configure the Pi’s WiFi.'
        : 'Set a Sentry controller password above first — it is what stops anyone who joins the network reconfiguring this Pi.',
    )
    controlToggle.update({
      value: nextProps.controlEnabled,
      onChange: (enabled) => {
        void setControlEnabled(enabled)
      },
      label: 'Allow hotspot control',
      accessibleName: 'Allow this Sentry to configure the Pi’s WiFi',
      disabled: !currentProps.authTokenConfigured,
    })
  }

  render(props)

  return {
    element: root,

    update(nextProps): void {
      render(nextProps)
    },

    destroy(): void {
      controlToggle.destroy()
      notice.destroy()
    },
  }
}
