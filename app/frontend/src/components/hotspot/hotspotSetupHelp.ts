import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { baseCopyButton } from '../base/baseCopyButton.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * What is still missing before a hotspot can start, and how to supply it.
 *
 * Two prerequisites, and they are satisfied in different places — which is the
 * whole reason this card exists rather than a form.
 *
 * `SENTRY_HOTSPOT_CONTROL_ENABLED` is `.env`-only, deliberately.
 * It is what makes driving the host's NetworkManager from this container
 * defensible instead of a privileged sidecar (ADR-0007): its entire value is
 * that turning it on requires shell access to the Pi. A toggle here would
 * delete the control it represents. It also could not work — `.env` is not
 * mounted into this container, and a container's environment is fixed when it
 * is created.
 *
 * The **controller password** is set in the UI, one section above this one. It
 * used to be `SENTRY_AUTH_TOKEN` in the same `.env`, and this card still said
 * so long after ADR-0010 removed it — telling operators to add a line that does
 * nothing.
 *
 * So the card does the part it usefully can: gives the shell step as one
 * command that can be pasted whole, and points at the UI for the part that
 * belongs there.
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

/**
 * The shell step, as one command rather than a line to paste into a file.
 *
 * `>> .env` then `up -d`, not "edit the file and restart it": `docker compose
 * restart` reuses the existing container and therefore its original
 * environment, so the change appears not to have worked. That trap has already
 * cost this project an hour of debugging on a real Pi.
 */
const CONTROL_ENABLED_COMMAND =
  "echo 'SENTRY_HOTSPOT_CONTROL_ENABLED=true' >> .env && docker compose up -d"

/** Builds a `HotspotSetupHelp`. `update` mutates the same notice in place. */
export function hotspotSetupHelp(props: HotspotSetupHelpProps): Component<HotspotSetupHelpProps> {
  const introParagraph = el('p', { class: 'm-0' }, [
    el('strong', { class: 'font-semibold' }, ['One-time setup on the Pi.']),
    ' Run this in Sentry’s directory — it appends the setting to ',
    el('code', { class: 'font-tabular' }, ['.env']),
    ' and recreates the container so it takes effect.',
  ])

  const envBlockPre = el(
    'pre',
    {
      class:
        'm-0 overflow-x-auto rounded-rack bg-ground-raised px-3 py-2 font-tabular text-[12px] leading-[1.7] text-ink-primary',
    },
    [el('code', {}, [CONTROL_ENABLED_COMMAND])],
  )

  const copyButton = baseCopyButton({
    value: CONTROL_ENABLED_COMMAND,
    accessibleName: 'Copy the setup command',
    label: 'Copy this command',
  })

  // The whole shell step, hidden once control is enabled. Grouped so intro,
  // command and button disappear together rather than leaving an orphan.
  const shellStep = el('div', { class: 'flex flex-col gap-3' }, [])

  const controlEnabledParagraph = el('p', { class: 'm-0 text-[11px] leading-[1.6]' }, [
    'Hotspot control is off by default because it is the one setting that lets this web API reconfigure the Pi’s own networking. Turning it on is deliberately something only someone with access to the Pi can do.',
  ])
  const passwordParagraph = el('p', { class: 'm-0 text-[11px] leading-[1.6]' }, [
    'A controller password is also required before a hotspot can start: once the network is up, anyone in range who has its WiFi password is on the same network as this API. Set one in ',
    el('strong', { class: 'font-semibold' }, ['Sentry controller password']),
    ' above — it is not a ',
    el('code', { class: 'font-tabular' }, ['.env']),
    ' setting.',
  ])

  shellStep.append(introParagraph, envBlockPre, copyButton.element, controlEnabledParagraph)

  const wrapper = el('div', { class: 'flex flex-col gap-3' }, [shellStep, passwordParagraph])

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

  function render(nextProps: HotspotSetupHelpProps): void {
    // Each prerequisite shows only while it is unmet. A satisfied one left on
    // screen reads as another thing still to do.
    setVisible(shellStep, !nextProps.controlEnabled)
    setVisible(passwordParagraph, !nextProps.authTokenConfigured)
  }

  render(props)

  return {
    element: notice.element,

    update(nextProps): void {
      render(nextProps)
    },

    destroy(): void {
      copyButton.destroy()
      notice.destroy()
    },
  }
}
