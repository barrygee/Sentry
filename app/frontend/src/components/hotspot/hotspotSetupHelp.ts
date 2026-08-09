import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { baseCopyButton } from '../base/baseCopyButton.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * The one-time `.env` step, shown in the UI instead of sending an operator to
 * the README to retype it.
 *
 * These two settings are shown rather than *edited* on purpose, and it is not
 * a shortcut not taken. `SENTRY_HOTSPOT_CONTROL_ENABLED` is what makes
 * driving the host's NetworkManager from this container defensible instead of
 * a privileged sidecar (ADR-0007) — its whole value is that turning it on
 * requires shell access to the Pi, so a form that flipped it would delete the
 * control it represents. `SENTRY_AUTH_TOKEN` is the API's own credential, and
 * this API is unauthenticated by default; an endpoint that could set it would
 * let anyone on the LAN lock the owner out.
 *
 * So the UI does the part it usefully can: says exactly which lines are
 * needed, and lets them be copied without transcription errors.
 */
export interface HotspotSetupHelpProps {
  /** Whether host WiFi control is switched on for this deployment. */
  controlEnabled: boolean
  /** Whether an API access token is configured. */
  authTokenConfigured: boolean
}

/** Only the lines actually missing — a satisfied prerequisite is not shown. */
function requiredLines(props: HotspotSetupHelpProps): string[] {
  const lines: string[] = []
  if (!props.controlEnabled) {
    lines.push('SENTRY_HOTSPOT_CONTROL_ENABLED=true')
  }
  if (!props.authTokenConfigured) {
    lines.push('SENTRY_AUTH_TOKEN=<a long random value>')
  }
  return lines
}

/** Builds a `HotspotSetupHelp`. `update` mutates the same notice in place. */
export function hotspotSetupHelp(props: HotspotSetupHelpProps): Component<HotspotSetupHelpProps> {
  const introLinesWord = document.createTextNode('')
  const introParagraph = el('p', { class: 'm-0' }, [
    el('strong', { class: 'font-semibold' }, ['One-time setup on the Pi.']),
    ' Add ',
    introLinesWord,
    ' to Sentry’s ',
    el('code', { class: 'font-tabular' }, ['.env']),
    ' file and restart it (',
    el('code', { class: 'font-tabular' }, ['docker compose restart']),
    ').',
  ])

  const envBlockText = document.createTextNode('')
  const envBlockPre = el(
    'pre',
    {
      class:
        'm-0 overflow-x-auto rounded-rack bg-ground-raised px-3 py-2 font-tabular text-[12px] leading-[1.7] text-ink-primary',
    },
    [el('code', {}, [envBlockText])],
  )

  const copyButton = baseCopyButton({
    value: '',
    accessibleName: 'Copy the required .env settings',
    label: 'Copy these settings',
  })

  const controlEnabledParagraph = el('p', { class: 'm-0 text-[11px] leading-[1.6]' }, [
    'Hotspot control is off by default because it is the one setting that lets this web API reconfigure the Pi’s own networking. Turning it on is deliberately something only someone with access to the Pi can do.',
  ])
  const authTokenParagraph = el('p', { class: 'm-0 text-[11px] leading-[1.6]' }, [
    'The access token is required before a hotspot can start: once the network is up, anyone in range who has its password is on the same network as this API.',
  ])

  const wrapper = el('div', { class: 'flex flex-col gap-3' }, [
    introParagraph,
    envBlockPre,
    copyButton.element,
    controlEnabledParagraph,
    authTokenParagraph,
  ])

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
    const lines = requiredLines(nextProps)
    introLinesWord.data = lines.length === 1 ? 'this line' : 'these lines'
    const envBlock = lines.join('\n')
    envBlockText.data = envBlock
    copyButton.update({
      value: envBlock,
      accessibleName: 'Copy the required .env settings',
      label: 'Copy these settings',
    })
    setVisible(controlEnabledParagraph, !nextProps.controlEnabled)
    setVisible(authTokenParagraph, !nextProps.authTokenConfigured)
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
