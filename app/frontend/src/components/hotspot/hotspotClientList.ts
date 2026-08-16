import type { Component } from '../../core/component.js'
import { releaseLease } from '../../state/hotspotStore.js'
import type { HotspotClient } from '../../api/client.js'
import { dhcpLeaseList } from '../base/dhcpLeaseList.js'
import type { DhcpLeaseListProps } from '../base/dhcpLeaseList.js'

/**
 * The hotspot's DHCP leases — the hotspot's wording over the shared list.
 *
 * The list itself lives in `base/dhcpLeaseList`, because the wired share
 * (ADR-0014) shows literally the same leases from the same dnsmasq. This module
 * is what makes those leases *the hotspot's*: it supplies the heading, the
 * copy that talks about radio range rather than cables, and the release call
 * that goes to the hotspot's own endpoint.
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

function toLeaseListProps(props: HotspotClientListProps): DhcpLeaseListProps {
  return {
    clients: props.clients,
    networkRunning: props.hotspotRunning,
    onRelease: (macAddress) => void releaseLease(macAddress),
    heading: 'Recent DHCP leases',
    persistKey: 'hotspot-leases',
    emptyStateDetail: 'Devices appear here shortly after they join the network.',
    runningNote: 'A lease is an address given out, not a device still in range.',
    stoppedNote: 'Left over from the last run — start the hotspot to release one.',
  }
}

/** Builds a `HotspotClientList`. `update` mutates the same lease list in place. */
export function hotspotClientList(
  props: HotspotClientListProps,
): Component<HotspotClientListProps> {
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
