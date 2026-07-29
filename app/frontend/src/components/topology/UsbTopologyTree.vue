<script setup lang="ts">
import { computed, provide } from 'vue'

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
  /** Focus recovered to a different node because the previous one disappeared. */
  focusRecovered: [nodeId: string | null]
}>()

const treeNavRoots = computed(() => props.roots.map(toTreeNavNode))

const treeNav = useTreeNavigation(treeNavRoots, {
  onActivate: (nodeId) => {
    const node = findNodeByPath(props.roots, nodeId)
    if (node?.device) {
      emit('activate', node.device.device_id)
    }
  },
  onFocusRecovered: (nodeId) => emit('focusRecovered', nodeId),
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
  <EmptyState
    v-if="roots.length === 0"
    title="No devices detected"
    detail="Connect an SDR to a USB port on this Pi."
  />
  <ul
    v-else
    role="tree"
    aria-label="USB topology"
    class="m-0 flex flex-col gap-0.5 rounded-rack border border-ground-hairline bg-ground-panel p-2 list-none"
  >
    <UsbTopologyNode v-for="node in roots" :key="node.path" :node="node" />
  </ul>
</template>
