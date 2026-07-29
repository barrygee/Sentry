import type { InjectionKey, Ref } from 'vue'

import type { FlatTreeNode } from '@/composables/useTreeNavigation'

/** Shared context `UsbTopologyTree` provides to every recursive `UsbTopologyNode`. */
export interface TopologyTreeContext {
  flatNodesById: Ref<Map<string, FlatTreeNode>>
  focusedId: Ref<string | null>
  isExpanded: (nodeId: string) => boolean
  toggleExpanded: (nodeId: string) => void
  tabIndexFor: (nodeId: string) => 0 | -1
  onKeydown: (event: KeyboardEvent, nodeId: string) => void
  onActivate: (nodeId: string) => void
  focusNode: (nodeId: string) => void
}

export const TOPOLOGY_TREE_CONTEXT_KEY: InjectionKey<TopologyTreeContext> =
  Symbol('topologyTreeContext')
