import type { DeviceStatus } from '@/api/client'
import type { TreeNavNode } from '@/composables/useTreeNavigation'
import type { TopologyNode } from '@/types/fleet'

/**
 * The current physical USB topology path for a device — only meaningful
 * while the device is actually plugged in. `usb_last_known` is a historical
 * record for the *card* (so an absent device can still show "last seen at
 * port X" text), not a coordinate in a physical-topology view: two
 * configured devices can share a last-known path (one now occupies it, one
 * merely used to), so it must never be used to place a node in the tree.
 * Returns null for any device that isn't physically present right now.
 */
export function effectiveTopologyPath(device: DeviceStatus): string | null {
  if (device.present && device.usb) {
    return device.usb.topology_path
  }
  return null
}

/**
 * Build the nested hub tree from the flat device list, keyed on
 * `topology_path` prefixes (e.g. "1-1.4.2" nests under "1-1.4" under "1-1").
 * This is what makes a dongle behind a USB extender appear as a child of
 * that hub — the hard requirement in the Sentry build brief.
 *
 * Only devices that are physically present (`present === true` with a
 * non-null `usb`) are placed in the tree — an absent device has no physical
 * location to render at, and rendering it under a stale `usb_last_known`
 * path risks colliding with (and silently hiding) whichever device
 * currently occupies that port. Absent devices remain visible via the card
 * list (`AbsentDeviceGroup`), which is the right place for a historical
 * record.
 *
 * Pure function over the snapshot; devices with no resolvable path (not
 * present, or present but with a topology path that doesn't match the
 * documented shape — should not occur for real hardware, but defends
 * against malformed fixture data) are returned separately via `unplaced`
 * rather than silently dropped. Two *present* devices should never physically
 * share a path, but if a bad snapshot ever claims they do, the collision is
 * resolved deterministically (lowest `device_id` wins the slot, the other
 * moves to `unplaced`) rather than depending on the order devices happened
 * to arrive in.
 */
export function buildTopologyTree(devices: readonly DeviceStatus[]): {
  roots: TopologyNode[]
  unplaced: DeviceStatus[]
} {
  const unplaced: DeviceStatus[] = []
  const nodesByPath = new Map<string, TopologyNode>()
  const rootPaths: string[] = []

  const placeableByPath = groupPresentDevicesByPath(devices, unplaced)

  for (const [fullPath, contenders] of placeableByPath) {
    const device = pickDeterministicWinner(contenders)
    for (const loser of contenders) {
      if (loser !== device) {
        unplaced.push(loser)
      }
    }

    const segments = splitPathSegments(fullPath)
    if (segments === null) {
      unplaced.push(device)
      continue
    }

    let parentChildren: TopologyNode[] | null = null
    for (let depth = 0; depth < segments.length; depth += 1) {
      const prefix = segments[depth]
      if (prefix === undefined) {
        continue
      }
      const isLeaf = depth === segments.length - 1
      let node = nodesByPath.get(prefix)
      if (!node) {
        node = { path: prefix, isHub: !isLeaf, device: null, children: [] }
        nodesByPath.set(prefix, node)
        if (parentChildren) {
          parentChildren.push(node)
        } else {
          rootPaths.push(prefix)
        }
      }
      if (isLeaf) {
        node.device = device
        node.isHub = false
      } else {
        node.isHub = true
      }
      parentChildren = node.children
    }
  }

  const roots = dedupeInOrder(rootPaths)
    .map((path) => nodesByPath.get(path))
    .filter((node): node is TopologyNode => node !== undefined)

  return { roots, unplaced }
}

/**
 * "1-1.4.2" -> ["1-1", "1-1.4", "1-1.4.2"] style segment keys, built by
 * splitting the bus prefix from the dotted port chain. Returns null for a
 * string that doesn't match the documented `bus-port.port...` shape rather
 * than guessing a placement for malformed data.
 */
function splitPathSegments(topologyPath: string): string[] | null {
  const match = /^(\d+)-(\d+(?:\.\d+)*)$/.exec(topologyPath)
  if (!match) {
    return null
  }
  const bus = match[1]
  const portChain = match[2]
  if (!bus || !portChain) {
    return null
  }
  const ports = portChain.split('.')
  return ports.map((_, index) => `${bus}-${ports.slice(0, index + 1).join('.')}`)
}

function dedupeInOrder(paths: readonly string[]): string[] {
  return Array.from(new Set(paths))
}

/**
 * Groups physically-present, placeable devices by their live topology path.
 * Present devices with no resolvable path (missing `usb`, or a
 * `topology_path` `effectiveTopologyPath` rejects) go straight to `unplaced`.
 * Absent devices are skipped entirely — they belong in the card list, not
 * the tree.
 */
function groupPresentDevicesByPath(
  devices: readonly DeviceStatus[],
  unplaced: DeviceStatus[],
): Map<string, DeviceStatus[]> {
  const placeableByPath = new Map<string, DeviceStatus[]>()
  for (const device of devices) {
    if (!device.present) {
      continue
    }
    const fullPath = effectiveTopologyPath(device)
    if (!fullPath) {
      unplaced.push(device)
      continue
    }
    const contenders = placeableByPath.get(fullPath)
    if (contenders) {
      contenders.push(device)
    } else {
      placeableByPath.set(fullPath, [device])
    }
  }
  return placeableByPath
}

/**
 * Deterministically resolves a path collision (should not occur for real
 * hardware — two devices cannot physically occupy the same USB port at
 * once) so the tree's contents never depend on snapshot iteration order.
 * Lowest `device_id` wins the slot; ties are impossible since `device_id`
 * is unique per device.
 */
function pickDeterministicWinner(contenders: readonly DeviceStatus[]): DeviceStatus {
  return contenders.reduce((winner, candidate) =>
    candidate.device_id < winner.device_id ? candidate : winner,
  )
}

/**
 * Maps a domain `TopologyNode` onto the generic `TreeNavNode` shape
 * `useTreeNavigation` operates on, so the keyboard-navigation composable
 * stays free of any fleet-specific typing.
 */
export function toTreeNavNode(node: TopologyNode): TreeNavNode {
  return {
    id: node.path,
    label: node.device ? node.device.name || node.device.device_id : `Hub ${node.path}`,
    children: node.children.map(toTreeNavNode),
  }
}
