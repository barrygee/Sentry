<script setup lang="ts">
import { computed, inject, nextTick, ref, watch } from 'vue'

import StatusDot from '@/components/base/StatusDot.vue'
import type { DeviceState } from '@/components/base/StatusDot.vue'
import type { TopologyNode } from '@/types/fleet'

import PortLug from './PortLug.vue'
import { TOPOLOGY_TREE_CONTEXT_KEY } from './topologyTreeContext'

const props = defineProps<{ node: TopologyNode }>()

const treeContext = inject(TOPOLOGY_TREE_CONTEXT_KEY)
if (!treeContext) {
  throw new Error('UsbTopologyNode must be rendered inside UsbTopologyTree')
}

const meta = computed(() => treeContext.flatNodesById.value.get(props.node.path) ?? null)
const isFocused = computed(() => treeContext.focusedId.value === props.node.path)
const isExpanded = computed(() =>
  props.node.children.length > 0 ? treeContext.isExpanded(props.node.path) : undefined,
)
const lastPortSegment = computed(() => {
  const segments = props.node.path.split('.')
  const lastSegment = segments[segments.length - 1]
  const portPart = lastSegment?.split('-').pop()
  return portPart ? Number.parseInt(portPart, 10) : null
})

const accessibleName = computed(() => {
  if (props.node.device) {
    const device = props.node.device
    const name = device.name || device.device_id
    const port = device.output ? `, port ${device.output.iq_port}` : ''
    return `${name}, ${device.state}${port}`
  }
  return `Hub, USB port ${props.node.path}`
})

const cardId = computed(() =>
  props.node.device ? `device-card-${props.node.device.device_id}` : undefined,
)

const itemElement = ref<HTMLLIElement | null>(null)

watch(isFocused, (focused) => {
  if (focused) {
    void nextTick(() => itemElement.value?.focus())
  }
})

function onClick(): void {
  treeContext.focusNode(props.node.path)
  if (props.node.children.length > 0) {
    treeContext.toggleExpanded(props.node.path)
  } else if (props.node.device) {
    treeContext.onActivate(props.node.path)
  }
}
</script>

<template>
  <!-- The rule's static checker can't evaluate a bound :tabindex expression, but roving
       tabindex (architecture §9.4) genuinely requires one: exactly one treeitem has
       tabindex 0 at a time, computed by useTreeNavigation.tabIndexFor. -->
  <!-- eslint-disable-next-line vuejs-accessibility/interactive-supports-focus -->
  <li
    :id="`topology-node-${node.path}`"
    ref="itemElement"
    role="treeitem"
    :aria-level="meta?.level ?? 1"
    :aria-setsize="meta?.setSize ?? 1"
    :aria-posinset="meta?.posInSet ?? 1"
    :aria-selected="isFocused"
    :aria-expanded="isExpanded"
    :aria-controls="cardId"
    :aria-label="accessibleName"
    :tabindex="treeContext.tabIndexFor(node.path)"
    class="list-none rounded-rack outline-none"
    @keydown="treeContext.onKeydown($event, node.path)"
    @click="onClick"
  >
    <div
      class="flex min-h-[36px] items-center gap-2 rounded-rack px-1.5 py-1"
      :class="isFocused ? 'bg-ground-raised' : 'hover:bg-ground-raised/60'"
      :style="{ paddingLeft: `${(meta?.level ?? 1) * 12}px` }"
    >
      <span aria-hidden="true" class="h-px w-3 bg-signal-cyan/50" />
      <PortLug v-if="lastPortSegment !== null" :port-number="lastPortSegment" />
      <template v-if="node.device">
        <StatusDot :state="node.device.state as DeviceState" />
        <span class="truncate font-mono text-xs">{{
          node.device.name || node.device.device_id
        }}</span>
      </template>
      <template v-else>
        <span class="font-condensed text-xs uppercase tracking-legend text-signal-slate">Hub</span>
      </template>
    </div>
    <ul v-if="node.children.length > 0 && isExpanded" role="group" class="m-0 list-none p-0">
      <UsbTopologyNode v-for="child in node.children" :key="child.path" :node="child" />
    </ul>
  </li>
</template>
