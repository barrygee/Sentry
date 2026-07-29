import type { DeviceStatus } from '@/api/client'
import type { TreeNavNode } from '@/composables/useTreeNavigation'
import type { TopologyNode } from '@/types/fleet'

/**
 * The effective USB topology path for a device: the live path when present,
 * else the last-known path so an absent-but-configured dongle still renders
 * in the tree at the port it was last seen (architecture §7.2, §9.1).
 */
export function effectiveTopologyPath(device: DeviceStatus): string | null {
  if (device.usb) {
    return device.usb.topology_path
  }
  if (device.usb_last_known && device.usb_last_known.topology_path) {
    return device.usb_last_known.topology_path
  }
  return null
}

/**
 * Build the nested hub tree from a flat device list, keyed on
 * `topology_path` prefixes (e.g. "1-1.4.2" nests under "1-1.4" under "1-1").
 * This is what makes a dongle behind a USB extender appear as a child of
 * that hub — the hard requirement in the Sentry build brief.
 *
 * Pure function over the snapshot; devices with no resolvable path (should
 * not occur for a real device, but defends against malformed fixture data)
 * are returned separately via `unplaced` rather than silently dropped.
 */
export function buildTopologyTree(devices: readonly DeviceStatus[]): {
  roots: TopologyNode[]
  unplaced: DeviceStatus[]
} {
  const unplaced: DeviceStatus[] = []
  const nodesByPath = new Map<string, TopologyNode>()
  const rootPaths: string[] = []

  for (const device of devices) {
    const fullPath = effectiveTopologyPath(device)
    if (!fullPath) {
      unplaced.push(device)
      continue
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
