import type { Component } from '../../core/component.js'
import { releaseLease } from '../../state/wiredStore.js'
import type { WiredClient } from '../../api/client.js'
import { dhcpLeaseList } from '../base/dhcpLeaseList.js'
import type { DhcpLeaseListProps } from '../base/dhcpLeaseList.js'

/**
 * The wired share's DHCP leases — the wired wording over the shared list.
 *
 * The list itself lives in `base/dhcpLeaseList`, which the hotspot uses too:
 * both features issue leases through the same NetworkManager dnsmasq, so the
 * rows, the sort and the three-state null handling are literally the same
 * problem. This module supplies what makes the leases *the cable's*: copy about
 * plugging in rather than joining, and the release call that goes to
 * `/api/wired`.
 */
export interface WiredClientListProps {
  /** `null` means unknown. Never render it as "nothing plugged in". */
  clients: WiredClient[] | null
  /**
   * Whether the share is currently up.
   *
   * Gates the release control: a release is a DHCPRELEASE to the share's
   * dnsmasq, which only exists while the shared connection is active. The lease
   * *file* outlives it, so a stopped share still lists the machines that took
   * an address the last time it ran.
   */
  sharingRunning: boolean
}

function toLeaseListProps(props: WiredClientListProps): DhcpLeaseListProps {
  return {
    clients: props.clients,
    networkRunning: props.sharingRunning,
    onRelease: (macAddress) => void releaseLease(macAddress),
    heading: 'Recent DHCP leases',
    persistKey: 'wired-leases',
    emptyStateDetail: 'Machines appear here shortly after you plug one into the shared port.',
    runningNote: 'A lease is an address given out, not a machine still plugged in.',
    stoppedNote: 'Left over from the last run — start wired sharing to release one.',
  }
}

/** Builds a `WiredClientList`. `update` mutates the same lease list in place. */
export function wiredClientList(props: WiredClientListProps): Component<WiredClientListProps> {
  const list = dhcpLeaseList(toLeaseListProps(props))

  return {
    element: list.element,

    update(nextProps): void {
      list.update(toLeaseListProps(nextProps))
    },

    destroy(): void {
      list.destroy()
    },
  }
}
