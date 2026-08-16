import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import type { HotspotClient } from '../../api/client.js'
import { confirmIconAction } from './confirmIconAction.js'
import type { ConfirmIconActionProps } from './confirmIconAction.js'
import { emptyState } from './emptyState.js'
import { monoValue } from './monoValue.js'
import { disclosureSection } from './disclosureSection.js'
import { statusBadge } from './statusBadge.js'
import type { StatusBadgeProps } from './statusBadge.js'

/**
 * The DHCP leases issued by one of Sentry's shared networks.
 *
 * Shared by the WiFi hotspot and the wired share, which issue leases through
 * the same NetworkManager dnsmasq and therefore have literally the same list to
 * show. Everything that differs between them — the heading, the persistence
 * key, the sentence under the list, what "release" is called — arrives as
 * props, so neither feature carries a near-copy of the other's list.
 *
 * Titled "leases", never "connected clients", and that wording is load-bearing.
 * A lease is not an association: a machine that walked away (or unplugged)
 * keeps its lease until it expires, and a statically-addressed one never
 * appears at all. Calling this a connection list would state something the data
 * cannot support, so expired leases are shown and marked rather than hidden.
 *
 * Three distinct states, and collapsing any two of them would lie:
 *  - `null`   — this host could not be asked at all.
 *  - `[]`     — it was asked, and nothing has taken a lease.
 *  - entries  — these machines were issued an address.
 */
export interface DhcpLeaseListProps {
  /** `null` means unknown. Never render it as "nothing connected". */
  clients: HotspotClient[] | null
  /**
   * Whether the network serving these leases is currently up.
   *
   * Gates the release control, which is only possible while it is: a release is
   * a DHCPRELEASE to the network's dnsmasq, and dnsmasq only exists while the
   * shared connection is active. The lease *file* outlives it, so a stopped
   * network still lists the machines that took an address the last time it ran
   * — offering a release button beside them produced a 409 every time.
   */
  networkRunning: boolean
  /** Releases one lease by MAC address. The store decides what that means. */
  onRelease: (macAddress: string) => void
  /** Section heading, also the list's accessible name. */
  heading: string
  /** Disclosure persistence key, so each list remembers its own open state. */
  persistKey: string
  /** How the empty state describes machines arriving, e.g. "join the network". */
  emptyStateDetail: string
  /** The one-line note shown under a populated list while the network is up. */
  runningNote: string
  /** The same note's counterpart while the network is down. */
  stoppedNote: string
}

/** One row's inputs: the lease, whether it can be released, and how. */
interface DhcpLeaseRowProps {
  client: HotspotClient
  networkRunning: boolean
  onRelease: (macAddress: string) => void
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
 * What a lease's badge should say, given whether its network is up.
 *
 * `expired` is a clock comparison on the server — `lease_expires_at_ms < now` —
 * and says nothing about whether the network is up. With it down there is no
 * dnsmasq, no network and nothing holding the address, so an unexpired lease
 * reading "Lease active" was true about the clock and misleading about reality.
 * It is described as held-but-not-in-force instead, and never in the `ok` tone,
 * which is reserved for a lease that is actually serving something.
 */
function leaseBadgeProps(client: HotspotClient, networkRunning: boolean): StatusBadgeProps {
  if (client.expired) {
    return { tone: 'neutral', children: ['Lease expired'] }
  }
  if (!networkRunning) {
    return { tone: 'neutral', children: ['Not in force'] }
  }
  return { tone: 'ok', children: ['Lease active'] }
}

function dhcpLeaseRow(props: DhcpLeaseRowProps): Component<DhcpLeaseRowProps> {
  let currentProps = props

  // Arm-then-confirm, like every other destructive control here. Worth the
  // extra tap: the row carries no undo, and the addresses beside each other
  // differ by a character or two.
  function releaseProps(): ConfirmIconActionProps {
    const client = currentProps.client
    const label = client.hostname ?? client.ip_address
    return {
      accessibleName: `Release the lease for ${label}`,
      confirmAccessibleName: `Confirm releasing the lease for ${label}`,
      cancelAccessibleName: `Cancel releasing the lease for ${label}`,
      armedAnnouncement: `Confirm releasing the lease for ${label}, or cancel. This frees the address; it does not disconnect the device.`,
      cancelledAnnouncement: `Releasing the lease for ${label} cancelled.`,
      onConfirm: () => {
        currentProps.onRelease(currentProps.client.mac_address)
      },
    }
  }

  const releaseAction = confirmIconAction(releaseProps())
  // Pushed to the row's trailing edge, so the controls line up down the list
  // however wide the hostnames are.
  releaseAction.element.classList.add('ml-auto')
  // Hidden rather than disabled while the network is down. A disabled control
  // still says "this is a thing you could do here"; with no dnsmasq to accept
  // the release, it is not one until the network is running again.
  setVisible(releaseAction.element, props.networkRunning)
  const ipMono = monoValue({ value: props.client.ip_address })
  const ipWrapper = el('span', { class: 'text-[13px] font-semibold text-ink-primary' }, [
    ipMono.element,
  ])
  const hostnameSpan = el('span', { class: 'text-[12px] text-ink-primary' }, [
    props.client.hostname ?? 'Unnamed device',
  ])
  const macMono = monoValue({ value: props.client.mac_address })
  const macWrapper = el('span', { class: 'text-[11px] text-signal-muted' }, [macMono.element])
  const badge = statusBadge(leaseBadgeProps(props.client, props.networkRunning))

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
      currentProps = nextProps
      const nextClient = nextProps.client
      releaseAction.update(releaseProps())
      setVisible(releaseAction.element, nextProps.networkRunning)
      ipMono.update({ value: nextClient.ip_address })
      setText(hostnameSpan, nextClient.hostname ?? 'Unnamed device')
      macMono.update({ value: nextClient.mac_address })
      badge.update(leaseBadgeProps(nextClient, nextProps.networkRunning))
    },

    destroy(): void {
      releaseAction.destroy()
      ipMono.destroy()
      macMono.destroy()
      badge.destroy()
    },
  }
}

/** Builds a `DhcpLeaseList`. `update` mutates the same lease list in place. */
export function dhcpLeaseList(props: DhcpLeaseListProps): Component<DhcpLeaseListProps> {
  const unreadableParagraph = el(
    'p',
    { class: 'm-0 text-[11px] leading-[1.6] text-signal-muted' },
    [
      'This Sentry cannot report leases — it has no readable lease file. That is not the same as nobody being connected.',
    ],
  )

  const empty = emptyState({
    title: 'No leases yet',
    detail: props.emptyStateDetail,
  })

  const list = el('ul', {
    class: 'm-0 flex list-none flex-col gap-2 p-0',
    attrs: { 'aria-label': props.heading },
  })
  const listController = keyedList<DhcpLeaseRowProps, string>(
    list,
    dhcpLeaseRow,
    (rowProps) => rowProps.client.mac_address,
  )

  // One line, and only one. Whichever fact the current state makes worth
  // stating wins: with the network off, why nothing can be released; with it
  // up, that a lease is not a device still present.
  const leaseNote = el('p', { class: 'm-0 text-[11px] leading-[1.6] text-signal-muted' }, [])

  // Collapsed by default. On a network that is off — the common case, and the
  // state the panel spends most of its life in — this section can only say
  // "no leases yet", and a permanently-open block saying nothing would be the
  // longest thing on the page.
  const root = disclosureSection({
    label: [props.heading],
    headingLevel: 3,
    tone: 'section',
    persistKey: props.persistKey,
    children: [unreadableParagraph, empty.element, list, leaseNote],
  })

  function render(nextProps: DhcpLeaseListProps): void {
    const sorted = sortedClients(nextProps.clients)
    setVisible(unreadableParagraph, nextProps.clients === null)
    setVisible(empty.element, nextProps.clients !== null && sorted.length === 0)
    setVisible(list, sorted.length > 0)
    listController.update(
      sorted.map((client) => ({
        client,
        networkRunning: nextProps.networkRunning,
        onRelease: nextProps.onRelease,
      })),
    )
    setText(leaseNote, nextProps.networkRunning ? nextProps.runningNote : nextProps.stoppedNote)
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
