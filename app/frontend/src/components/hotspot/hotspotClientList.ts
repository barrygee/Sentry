import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import { releaseLease } from '../../state/hotspotStore.js'
import type { HotspotClient } from '../../api/client.js'
import { confirmIconAction } from '../base/confirmIconAction.js'
import type { ConfirmIconActionProps } from '../base/confirmIconAction.js'
import { emptyState } from '../base/emptyState.js'
import { monoValue } from '../base/monoValue.js'
import { disclosureSection } from '../base/disclosureSection.js'
import { statusBadge } from '../base/statusBadge.js'
import type { StatusBadgeProps } from '../base/statusBadge.js'

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
  /**
   * Whether the hotspot is currently up.
   *
   * Gates the release control, which is only possible while it is: a release is
   * a DHCPRELEASE to the AP's dnsmasq, and dnsmasq only exists while the shared
   * connection is active. The lease *file* outlives it, so a stopped hotspot
   * still lists the devices that joined the last time it ran — offering a
   * release button beside them produced a 409 `hotspot_not_running` every time.
   */
  hotspotRunning: boolean
}

/** One row's inputs: the lease, and whether it can currently be released. */
interface HotspotClientRowProps {
  client: HotspotClient
  hotspotRunning: boolean
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

/**
 * What a lease's badge should say, given the hotspot's state.
 *
 * `expired` is a clock comparison on the server — `lease_expires_at_ms <
 * now` — and says nothing about whether the hotspot is up. With the AP down
 * there is no dnsmasq, no network and nothing holding the address, so an
 * unexpired lease reading "Lease active" was true about the clock and
 * misleading about reality. It is described as held-but-not-in-force instead,
 * and never in the `ok` tone, which is reserved for a lease that is actually
 * serving something.
 */
function leaseBadgeProps(client: HotspotClient, hotspotRunning: boolean): StatusBadgeProps {
  if (client.expired) {
    return { tone: 'neutral', children: ['Lease expired'] }
  }
  if (!hotspotRunning) {
    return { tone: 'neutral', children: ['Not in force'] }
  }
  return { tone: 'ok', children: ['Lease active'] }
}

function hotspotClientRow(props: HotspotClientRowProps): Component<HotspotClientRowProps> {
  let currentClient = props.client

  // Arm-then-confirm, like every other destructive control here. Worth the
  // extra tap: the row carries no undo, and the addresses beside each other
  // differ by a character or two.
  function releaseProps(): ConfirmIconActionProps {
    const label = currentClient.hostname ?? currentClient.ip_address
    return {
      accessibleName: `Release the lease for ${label}`,
      confirmAccessibleName: `Confirm releasing the lease for ${label}`,
      cancelAccessibleName: `Cancel releasing the lease for ${label}`,
      armedAnnouncement: `Confirm releasing the lease for ${label}, or cancel. This frees the address; it does not disconnect the device.`,
      cancelledAnnouncement: `Releasing the lease for ${label} cancelled.`,
      onConfirm: () => {
        void releaseLease(currentClient.mac_address)
      },
    }
  }

  const releaseAction = confirmIconAction(releaseProps())
  // Pushed to the row's trailing edge, so the controls line up down the list
  // however wide the hostnames are.
  releaseAction.element.classList.add('ml-auto')
  // Hidden rather than disabled while the hotspot is down. A disabled control
  // still says "this is a thing you could do here"; with no dnsmasq to accept
  // the release, it is not one until the hotspot is running again.
  setVisible(releaseAction.element, props.hotspotRunning)
  const ipMono = monoValue({ value: props.client.ip_address })
  const ipWrapper = el('span', { class: 'text-[13px] font-semibold text-ink-primary' }, [
    ipMono.element,
  ])
  const hostnameSpan = el('span', { class: 'text-[12px] text-ink-primary' }, [
    props.client.hostname ?? 'Unnamed device',
  ])
  const macMono = monoValue({ value: props.client.mac_address })
  const macWrapper = el('span', { class: 'text-[11px] text-signal-muted' }, [macMono.element])
  const badge = statusBadge(leaseBadgeProps(props.client, props.hotspotRunning))

  const root = el(
    'li',
    {
      class: 'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-rack bg-ground-raised px-3 py-2',
    },
    [ipWrapper, hostnameSpan, macWrapper, badge.element, releaseAction.element],
  )

  return {
    element: root,

    update(nextProps): void {
      const nextClient = nextProps.client
      currentClient = nextClient
      releaseAction.update(releaseProps())
      setVisible(releaseAction.element, nextProps.hotspotRunning)
      ipMono.update({ value: nextClient.ip_address })
      setText(hostnameSpan, nextClient.hostname ?? 'Unnamed device')
      macMono.update({ value: nextClient.mac_address })
      badge.update(leaseBadgeProps(nextClient, nextProps.hotspotRunning))
    },

    destroy(): void {
      releaseAction.destroy()
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
  const unreadableParagraph = el(
    'p',
    { class: 'm-0 text-[11px] leading-[1.6] text-signal-muted' },
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
  const listController = keyedList<HotspotClientRowProps, string>(
    list,
    hotspotClientRow,
    (rowProps) => rowProps.client.mac_address,
  )

  // One line, and only one. This was two paragraphs — what a lease is, and why
  // the release controls are missing — which between them said more about the
  // list than the list itself did. Whichever fact the current state makes
  // worth stating wins: with the hotspot off, why nothing can be released;
  // with it up, that a lease is not a device in range.
  const leaseNote = el('p', { class: 'm-0 text-[11px] leading-[1.6] text-signal-muted' }, [])

  // Collapsed by default. On a hotspot that is off — the common case, and the
  // state the panel spends most of its life in — this section can only say
  // "no leases yet", and a permanently-open block saying nothing was the
  // longest thing on the page.
  const root = disclosureSection({
    label: ['Recent DHCP leases'],
    headingLevel: 3,
    tone: 'section',
    persistKey: 'hotspot-leases',
    children: [unreadableParagraph, empty.element, list, leaseNote],
  })

  function render(nextProps: HotspotClientListProps): void {
    const sorted = sortedClients(nextProps.clients)
    setVisible(unreadableParagraph, nextProps.clients === null)
    setVisible(empty.element, nextProps.clients !== null && sorted.length === 0)
    setVisible(list, sorted.length > 0)
    listController.update(
      sorted.map((client) => ({ client, hotspotRunning: nextProps.hotspotRunning })),
    )
    setText(
      leaseNote,
      nextProps.hotspotRunning
        ? 'A lease is an address given out, not a device still in range.'
        : 'Left over from the last run — start the hotspot to release one.',
    )
    setVisible(leaseNote, nextProps.clients !== null && sorted.length > 0)
  }

  render(props)

  return {
    element: root.element,

    update(nextProps): void {
      render(nextProps)
    },

    destroy(): void {
      root.destroy()
      empty.destroy()
      listController.destroy()
    },
  }
}
