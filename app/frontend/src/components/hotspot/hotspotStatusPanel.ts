import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { HotspotState } from '../../api/client.js'
import { baseCopyButton } from '../base/baseCopyButton.js'
import { dataCell } from '../base/dataCell.js'
import { monoValue } from '../base/monoValue.js'
import { statusBadge } from '../base/statusBadge.js'
import type { StatusBadgeTone } from '../base/statusBadge.js'

/**
 * What the hotspot is doing right now, and — the part that actually matters
 * — the address a joined client has to be given.
 *
 * That address is the whole point of the feature: Sentinel has no discovery,
 * so a human reads this number off the screen and types it into Sentinel's
 * SDR form on another machine. It gets the largest treatment on the panel and
 * a copy button, because it is the one value here that leaves the browser.
 */
export interface HotspotStatusPanelProps {
  state: HotspotState
}

/**
 * What the hotspot is doing, in the operator's terms.
 *
 * "Unavailable" used to cover the first two cases below, which are not the same
 * thing at all and want different responses. Worse, the commoner of them is the
 * shipped default: a fresh Pi has hotspot control switched off, so the first
 * thing an operator ever saw here was a red word suggesting something had
 * broken. Nothing had.
 */
function statusLabel(state: HotspotState): string {
  // No badge while control is switched off. It used to say so here, which made
  // sense when turning it on meant a shell command elsewhere — but the switch
  // now sits directly below (ADR-0013), already labelled and already showing
  // its own state. A badge repeating it is a second, staler voice for the same
  // fact.
  if (!state.control_enabled) return ''
  // Control is on, but NetworkManager cannot be reached. This one *is* wrong.
  if (!state.available) return 'WiFi control unavailable'
  if (!state.configured) return 'Not set up'
  if (state.active) return state.pending_confirmation ? 'On trial' : 'Running'
  return 'Stopped'
}

function statusTone(state: HotspotState): StatusBadgeTone {
  // Neutral, not danger: an operator who has not opted in has nothing to fix.
  if (!state.control_enabled) return 'neutral'
  if (!state.available) return 'danger'
  if (!state.configured) return 'neutral'
  if (state.active) return state.pending_confirmation ? 'warn' : 'ok'
  return 'neutral'
}

function bandLabel(state: HotspotState): string {
  return state.band === 'a' ? '5 GHz' : '2.4 GHz'
}

function securityLabel(state: HotspotState): string {
  return state.security === 'wpa3' ? 'WPA3-Personal' : 'WPA2-Personal'
}

function channelLabel(state: HotspotState): string {
  return state.channel === 0 ? 'Automatic' : String(state.channel)
}

/** Builds a `HotspotStatusPanel`. `update` mutates the same status readout in place. */
export function hotspotStatusPanel(
  props: HotspotStatusPanelProps,
): Component<HotspotStatusPanelProps> {
  const badge = statusBadge({ tone: statusTone(props.state), children: [statusLabel(props.state)] })
  const hiddenBadge = statusBadge({ tone: 'info', children: ['Hidden'] })

  // Captioned like every other readout in this panel. It was a bare badge on
  // an unlabelled row, which made the one value an operator looks at first the
  // only one that did not say what it was. The SSID sat beside it and is gone:
  // the form's own "Network name (SSID)" field states it a few lines below,
  // and two copies of the same string invite them to disagree.
  const statusValue = el('span', { class: 'flex flex-wrap items-center gap-2' }, [
    badge.element,
    hiddenBadge.element,
  ])
  const statusCell = dataCell({
    label: 'Status',
    labelTag: 'dt',
    valueTag: 'dd',
    children: [statusValue],
  })
  // Its own list rather than a seventh cell in the grid below: that grid is
  // hidden until the hotspot is configured, and the status is exactly what an
  // unconfigured one still needs to report. Same grid classes, so the caption
  // lines up with the column beneath it.
  const statusList = el('dl', { class: 'm-0 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3' }, [
    statusCell.element,
  ])

  // The address a client dials. Given its own block rather than a cell in the
  // grid below, because it is the value someone is copying by hand onto
  // another machine, not a detail they are skimming.
  const addressLabel = el(
    'span',
    {
      class:
        'select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary',
    },
    ['Address for clients'],
  )
  const addressMono = monoValue({ value: '' })
  const addressMonoWrapper = el('span', { class: 'text-[18px] font-semibold text-ink-primary' }, [
    addressMono.element,
  ])
  const addressCopyButton = baseCopyButton({
    value: '',
    accessibleName: 'Copy the hotspot address for clients',
  })
  const addressRow = el('div', { class: 'flex flex-wrap items-center gap-3' }, [
    addressMonoWrapper,
    addressCopyButton.element,
  ])
  const addressHint = el('p', { class: 'm-0 text-[11px] leading-[1.6] text-signal-muted' }, [
    'Join this network, then enter this address in Sentinel’s SDR settings with each device’s port.',
  ])
  const addressBlock = el('div', { class: 'flex flex-col gap-2' }, [
    addressLabel,
    addressRow,
    addressHint,
  ])

  const interfaceCell = dataCell({ label: 'Interface', labelTag: 'dt', valueTag: 'dd', value: '—' })
  const securityCell = dataCell({ label: 'Security', labelTag: 'dt', valueTag: 'dd', value: '' })
  const bandCell = dataCell({ label: 'Band', labelTag: 'dt', valueTag: 'dd', value: '' })
  const channelCell = dataCell({ label: 'Channel', labelTag: 'dt', valueTag: 'dd', value: '' })
  const bootCell = dataCell({ label: 'Starts on boot', labelTag: 'dt', valueTag: 'dd', value: '' })
  const passwordCell = dataCell({ label: 'Password', labelTag: 'dt', valueTag: 'dd', value: '' })
  const detailsList = el('dl', { class: 'm-0 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3' }, [
    interfaceCell.element,
    securityCell.element,
    bandCell.element,
    channelCell.element,
    bootCell.element,
    passwordCell.element,
  ])

  const root = el('div', { class: 'flex flex-col gap-4' }, [statusList, addressBlock, detailsList])

  function render(state: HotspotState): void {
    setVisible(badge.element, state.control_enabled)
    badge.update({ tone: statusTone(state), children: [statusLabel(state)] })
    setVisible(hiddenBadge.element, state.configured && state.hidden)

    const showAddress = Boolean(state.gateway_address) && state.active
    setVisible(addressBlock, showAddress)
    if (state.gateway_address) {
      addressMono.update({ value: state.gateway_address })
      addressCopyButton.update({
        value: state.gateway_address,
        accessibleName: 'Copy the hotspot address for clients',
      })
    }

    setVisible(detailsList, state.configured)
    interfaceCell.update({
      label: 'Interface',
      labelTag: 'dt',
      valueTag: 'dd',
      value: state.interface ?? '—',
    })
    securityCell.update({
      label: 'Security',
      labelTag: 'dt',
      valueTag: 'dd',
      value: securityLabel(state),
    })
    bandCell.update({ label: 'Band', labelTag: 'dt', valueTag: 'dd', value: bandLabel(state) })
    channelCell.update({
      label: 'Channel',
      labelTag: 'dt',
      valueTag: 'dd',
      value: channelLabel(state),
    })
    bootCell.update({
      label: 'Starts on boot',
      labelTag: 'dt',
      valueTag: 'dd',
      value: state.enabled ? 'Yes' : 'No',
    })
    passwordCell.update({
      label: 'Password',
      labelTag: 'dt',
      valueTag: 'dd',
      value: state.passphrase_set ? 'Set' : 'Not set',
    })
  }

  render(props.state)

  return {
    element: root,

    update(nextProps): void {
      render(nextProps.state)
    },

    destroy(): void {
      badge.destroy()
      hiddenBadge.destroy()
      statusCell.destroy()
      addressMono.destroy()
      addressCopyButton.destroy()
      interfaceCell.destroy()
      securityCell.destroy()
      bandCell.destroy()
      channelCell.destroy()
      bootCell.destroy()
      passwordCell.destroy()
    },
  }
}
