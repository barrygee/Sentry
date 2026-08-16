import { el, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import type { WiredShareState } from '../../api/client.js'
import { baseCopyButton } from '../base/baseCopyButton.js'
import { dataCell } from '../base/dataCell.js'
import { monoValue } from '../base/monoValue.js'

/**
 * What wired sharing is doing right now, and — the part that actually matters
 * — the address a cabled machine has to be given.
 *
 * That address is the whole point of the feature: Sentinel has no discovery, so
 * a human reads this number off the screen and types it into Sentinel's SDR
 * form on the laptop they just plugged in. It gets the largest treatment on the
 * panel and a copy button, because it is the one value here that leaves the
 * browser.
 *
 * The cable readout is the wired-only cell and earns its place: "nothing is
 * plugged in" is by far the commonest reason a share that came up perfectly has
 * no clients on it, and there is no equivalent question to ask of a radio.
 */
export interface WiredStatusPanelProps {
  state: WiredShareState
}

/**
 * Three answers, not two. `null` means the host did not report the carrier at
 * all, which must not be rendered as "unplugged" — that would state a fact
 * about the port that nothing has established.
 */
function cableLabel(state: WiredShareState): string {
  if (state.carrier_up === null || state.carrier_up === undefined) return 'Unknown'
  return state.carrier_up ? 'Plugged in' : 'Nothing plugged in'
}

export function wiredStatusPanel(props: WiredStatusPanelProps): Component<WiredStatusPanelProps> {
  // The address a cabled machine dials. Given its own block rather than a cell
  // in the grid below, because it is the value someone is copying by hand onto
  // another machine, not a detail they are skimming.
  const addressLabel = el(
    'span',
    {
      class:
        'select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary',
    },
    ['Sentry IP'],
  )
  const addressMono = monoValue({ value: '' })
  const addressMonoWrapper = el(
    'span',
    { class: 'font-tabular text-[12.5px] leading-[24px] tracking-readout text-ink-primary' },
    [addressMono.element],
  )
  const addressCopyButton = baseCopyButton({
    value: '',
    accessibleName: 'Copy the Sentry IP',
  })
  const addressRow = el('div', { class: 'flex flex-wrap items-center gap-2' }, [
    addressMonoWrapper,
    addressCopyButton.element,
  ])
  const addressBlock = el('div', { class: 'flex flex-col gap-2' }, [addressLabel, addressRow])

  const interfaceCell = dataCell({ label: 'Port', labelTag: 'dt', valueTag: 'dd', value: '—' })
  const cableCell = dataCell({ label: 'Cable', labelTag: 'dt', valueTag: 'dd', value: '' })
  const bootCell = dataCell({ label: 'Starts on boot', labelTag: 'dt', valueTag: 'dd', value: '' })
  const detailsList = el('dl', { class: 'm-0 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3' }, [
    interfaceCell.element,
    cableCell.element,
    bootCell.element,
  ])

  const root = el('div', { class: 'flex flex-col gap-4' }, [addressBlock, detailsList])

  function render(state: WiredShareState): void {
    // Shown only while sharing is actually up, matching the hotspot: an address
    // printed beside a stopped share is one nothing will answer on.
    const showAddress = Boolean(state.gateway_address) && state.active
    setVisible(addressBlock, showAddress)
    if (state.gateway_address) {
      addressMono.update({ value: state.gateway_address })
      addressCopyButton.update({
        value: state.gateway_address,
        accessibleName: 'Copy the wired address for cabled machines',
      })
    }

    setVisible(detailsList, state.configured)
    interfaceCell.update({
      label: 'Port',
      labelTag: 'dt',
      valueTag: 'dd',
      value: state.interface ?? '—',
    })
    cableCell.update({
      label: 'Cable',
      labelTag: 'dt',
      valueTag: 'dd',
      value: cableLabel(state),
    })
    bootCell.update({
      label: 'Starts on boot',
      labelTag: 'dt',
      valueTag: 'dd',
      value: state.enabled ? 'Yes' : 'No',
    })
  }

  render(props.state)

  return {
    element: root,

    update(nextProps): void {
      render(nextProps.state)
    },

    destroy(): void {
      addressMono.destroy()
      addressCopyButton.destroy()
      interfaceCell.destroy()
      cableCell.destroy()
      bootCell.destroy()
    },
  }
}
