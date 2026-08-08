import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import type { HotspotClient } from '../../api/client.js'
import { emptyState } from '../base/emptyState.js'
import { monoValue } from '../base/monoValue.js'
import { nextElementId } from '../base/idGenerator.js'
import { sectionHeading } from '../base/sectionHeading.js'
import { statusBadge } from '../base/statusBadge.js'

/**
 * The hotspot's DHCP leases.
 *
 * Titled "Recent DHCP leases", not "Connected clients", and that wording is
 * load-bearing. A lease is not an association: a client that walked out of
 * range keeps its lease until it expires, and a statically-addressed client
 * never appears at all. Calling this a connection list would state something
 * the data cannot support, so expired leases are shown and marked rather than
 * hidden.
 *
 * Three distinct states, and collapsing any two of them would lie:
 *  - `null`   — this host could not be asked at all.
 *  - `[]`     — it was asked, and nothing has taken a lease.
 *  - entries  — these machines were issued an address.
 */
export interface HotspotClientListProps {
  /** `null` means unknown. Never render it as "none connected". */
  clients: HotspotClient[] | null
}

function sortedClients(clients: HotspotClient[] | null): HotspotClient[] {
  if (clients === null) {
    return []
  }
  return [...clients].sort((left, right) => {
    // Live leases first, then most-recently-expiring, so the machines that
    // are probably actually there sit at the top.
    if (left.expired !== right.expired) return left.expired ? 1 : -1
    return right.lease_expires_at_ms - left.lease_expires_at_ms
  })
}

function hotspotClientRow(client: HotspotClient): Component<HotspotClient> {
  const ipMono = monoValue({ value: client.ip_address })
  const ipWrapper = el('span', { class: 'text-[13px] font-semibold text-ink-primary' }, [
    ipMono.element,
  ])
  const hostnameSpan = el('span', { class: 'text-[12px] text-ink-primary' }, [
    client.hostname ?? 'Unnamed device',
  ])
  const macMono = monoValue({ value: client.mac_address })
  const macWrapper = el('span', { class: 'text-[11px] text-signal-muted' }, [macMono.element])
  const badge = statusBadge({
    tone: client.expired ? 'neutral' : 'ok',
    children: [client.expired ? 'Lease expired' : 'Lease active'],
  })

  const root = el(
    'li',
    {
      class: 'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-rack bg-ground-raised px-3 py-2',
    },
    [ipWrapper, hostnameSpan, macWrapper, badge.element],
  )

  return {
    element: root,

    update(nextClient): void {
      ipMono.update({ value: nextClient.ip_address })
      setText(hostnameSpan, nextClient.hostname ?? 'Unnamed device')
      macMono.update({ value: nextClient.mac_address })
      badge.update({
        tone: nextClient.expired ? 'neutral' : 'ok',
        children: [nextClient.expired ? 'Lease expired' : 'Lease active'],
      })
    },

    destroy(): void {
      ipMono.destroy()
      macMono.destroy()
      badge.destroy()
    },
  }
}

/** Builds a `HotspotClientList`. `update` mutates the same lease list in place. */
export function hotspotClientList(
  props: HotspotClientListProps,
): Component<HotspotClientListProps> {
  const headingId = nextElementId('hotspot-clients-heading')
  const heading = sectionHeading({ level: 3, children: ['Recent DHCP leases'] })
  heading.element.id = headingId

  const unreadableParagraph = el(
    'p',
    { class: 'm-0 text-[12px] leading-[1.6] text-signal-muted' },
    [
      'This Sentry cannot report leases — it has no readable lease file. That is not the same as nobody being connected.',
    ],
  )

  const empty = emptyState({
    title: 'No leases yet',
    detail: 'Devices appear here shortly after they join the network.',
  })

  const list = el('ul', {
    class: 'm-0 flex list-none flex-col gap-2 p-0',
    attrs: { 'aria-label': 'Recent DHCP leases' },
  })
  const listController = keyedList<HotspotClient, string>(
    list,
    hotspotClientRow,
    (client) => client.mac_address,
  )

  const trailingNote = el('p', { class: 'm-0 text-[11px] text-signal-muted' }, [
    'A lease shows that a device was given an address, not that it is still in range.',
  ])

  const root = el(
    'section',
    { class: 'flex flex-col gap-3', attrs: { 'aria-labelledby': headingId } },
    [heading.element, unreadableParagraph, empty.element, list, trailingNote],
  )

  function render(clients: HotspotClient[] | null): void {
    const sorted = sortedClients(clients)
    setVisible(unreadableParagraph, clients === null)
    setVisible(empty.element, clients !== null && sorted.length === 0)
    setVisible(list, sorted.length > 0)
    listController.update(sorted)
    setVisible(trailingNote, clients !== null && sorted.length > 0)
  }

  render(props.clients)

  return {
    element: root,

    update(nextProps): void {
      render(nextProps.clients)
    },

    destroy(): void {
      heading.destroy()
      empty.destroy()
      listController.destroy()
    },
  }
}
