import { el, setText, setVisible } from '../../core/dom.js'
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

function statusLabel(state: HotspotState): string {
  if (!state.available) return 'Unavailable'
  if (!state.configured) return 'Not set up'
  if (state.active) return state.pending_confirmation ? 'On trial' : 'Running'
  return 'Stopped'
}

function statusTone(state: HotspotState): StatusBadgeTone {
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
  const ssidSpan = el(
    'span',
    { class: 'font-tabular text-[14px] font-semibold text-ink-primary' },
    [],
  )
  const hiddenBadge = statusBadge({ tone: 'info', children: ['Hidden'] })
  const topRow = el('div', { class: 'flex flex-wrap items-center gap-3' }, [
    badge.element,
    ssidSpan,
    hiddenBadge.element,
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

  const root = el('div', { class: 'flex flex-col gap-4' }, [topRow, addressBlock, detailsList])

  function render(state: HotspotState): void {
    badge.update({ tone: statusTone(state), children: [statusLabel(state)] })
    setVisible(ssidSpan, Boolean(state.ssid))
    setText(ssidSpan, state.ssid ?? '')
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
