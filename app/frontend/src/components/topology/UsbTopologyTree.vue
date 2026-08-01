<script setup lang="ts">
import { computed, nextTick, provide, ref } from 'vue'

import EmptyState from '@/components/base/EmptyState.vue'
import { useTreeNavigation } from '@/composables/useTreeNavigation'
import type { TopologyNode } from '@/types/fleet'
import { toTreeNavNode } from '@/utils/topology'

import { TOPOLOGY_TREE_CONTEXT_KEY } from './topologyTreeContext'
import UsbTopologyNode from './UsbTopologyNode.vue'

const props = defineProps<{ roots: TopologyNode[] }>()

const emit = defineEmits<{
  /** A leaf node was activated (Enter/Space/click) — move focus to its device card. */
  activate: [deviceId: string]
  /**
   * Focus genuinely moved because the previously-focused node disappeared —
   * carries the exact sentence to announce, since only this component knows
   * both the destination node's label and whether the tree emptied
   * entirely (in which case focus moves to `emptyStateElement` below, not
   * to a tree node at all).
   */
  focusRecovered: [message: string]
}>()

const emptyStateElement = ref<HTMLDivElement | null>(null)

const treeNavRoots = computed(() => props.roots.map(toTreeNavNode))

const treeNav = useTreeNavigation(treeNavRoots, {
  onActivate: (nodeId) => {
    const node = findNodeByPath(props.roots, nodeId)
    if (node?.device) {
      emit('activate', node.device.device_id)
    }
  },
  onFocusRecovered: (nodeId) => {
    if (nodeId === null) {
      // The tree emptied entirely — nothing left to move focus to inside
      // it, so give the empty-state panel a real focus target rather than
      // letting focus silently fall back to `<body>`.
      void nextTick(() => emptyStateElement.value?.focus())
      emit('focusRecovered', 'All devices disconnected. Focus moved to the topology panel.')
      return
    }
    const survivingNode = treeNav.flatNodes.value.find((node) => node.id === nodeId)
    emit('focusRecovered', `Focus moved to ${survivingNode?.label ?? 'a nearby item'}.`)
  },
})

const flatNodesById = computed(
  () => new Map(treeNav.flatNodes.value.map((node) => [node.id, node])),
)

provide(TOPOLOGY_TREE_CONTEXT_KEY, {
  flatNodesById,
  focusedId: treeNav.focusedId,
  isExpanded: treeNav.isExpanded,
  toggleExpanded: treeNav.toggleExpanded,
  tabIndexFor: treeNav.tabIndexFor,
  onKeydown: treeNav.onKeydown,
  onActivate: (nodeId) => {
    const node = findNodeByPath(props.roots, nodeId)
    if (node?.device) {
      emit('activate', node.device.device_id)
    }
  },
  focusNode: (nodeId) => {
    treeNav.focusedId.value = nodeId
  },
})

function findNodeByPath(nodes: TopologyNode[], path: string): TopologyNode | null {
  for (const node of nodes) {
    if (node.path === path) return node
    const found = findNodeByPath(node.children, path)
    if (found) return found
  }
  return null
}
</script>

<template>
  <div
    v-if="roots.length === 0"
    ref="emptyStateElement"
    tabindex="-1"
    class="rounded-rack outline-none"
    aria-label="Topology panel, no devices detected"
  >
    <EmptyState title="No devices detected" detail="Connect an SDR to a USB port on this Pi." />
  </div>
  <ul
    v-else
    role="tree"
    aria-label="USB topology"
    class="m-0 flex flex-col gap-0.5 rounded-rack border border-ground-hairline bg-ground-panel p-2 list-none"
  >
    <UsbTopologyNode v-for="node in roots" :key="node.path" :node="node" />
  </ul>
</template>
