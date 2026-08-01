import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

/** The minimal shape `useTreeNavigation` needs — domain-agnostic on purpose. */
export interface TreeNavNode {
  id: string
  label: string
  children: TreeNavNode[]
}

export interface FlatTreeNode {
  id: string
  label: string
  level: number
  hasChildren: boolean
  expanded: boolean
  parentId: string | null
  setSize: number
  posInSet: number
}

export interface TreeNavigationOptions {
  /** Called when Enter/Space activates a node — the caller moves focus to the matching device card. */
  onActivate?: (nodeId: string) => void
  /** Called after focus moves because the previously-focused node disappeared, for a live announcement. */
  onFocusRecovered?: (nodeId: string | null) => void
}

export interface TreeNavigationHandle {
  flatNodes: ComputedRef<FlatTreeNode[]>
  focusedId: Ref<string | null>
  isExpanded: (nodeId: string) => boolean
  toggleExpanded: (nodeId: string) => void
  tabIndexFor: (nodeId: string) => 0 | -1
  onKeydown: (event: KeyboardEvent, nodeId: string) => void
}

/**
 * ARIA Authoring Practices *Tree View* keyboard behaviour (architecture
 * §9.4): a single roving tab stop, arrow-key traversal of the currently
 * *visible* nodes only, Home/End, `*` to expand all siblings, Enter/Space to
 * activate, and type-ahead. Nodes are addressed by stable string id (never
 * array index) so live hotplug updates never let Vue recycle a DOM node
 * between two different dongles.
 */
export function useTreeNavigation(
  roots: Ref<TreeNavNode[]>,
  options: TreeNavigationOptions = {},
): TreeNavigationHandle {
  const collapsedIds = ref<Set<string>>(new Set())
  const focusedId = ref<string | null>(null)
  let typeaheadBuffer = ''
  let typeaheadResetTimeoutId: ReturnType<typeof setTimeout> | null = null

  function isExpanded(nodeId: string): boolean {
    return !collapsedIds.value.has(nodeId)
  }

  function toggleExpanded(nodeId: string): void {
    const next = new Set(collapsedIds.value)
    if (next.has(nodeId)) {
      next.delete(nodeId)
    } else {
      next.add(nodeId)
    }
    collapsedIds.value = next
  }

  const flatNodes = computed<FlatTreeNode[]>(() => {
    const result: FlatTreeNode[] = []
    const walk = (nodes: TreeNavNode[], level: number, parentId: string | null): void => {
      nodes.forEach((node, index) => {
        const hasChildren = node.children.length > 0
        result.push({
          id: node.id,
          label: node.label,
          level,
          hasChildren,
          expanded: hasChildren ? isExpanded(node.id) : false,
          parentId,
          setSize: nodes.length,
          posInSet: index + 1,
        })
        if (hasChildren && isExpanded(node.id)) {
          walk(node.children, level + 1, node.id)
        }
      })
    }
    walk(roots.value, 1, null)
    return result
  })

  // Seed the initial roving tab stop once nodes exist. Kept out of the
  // `flatNodes` getter itself — a computed that writes to a ref it doesn't
  // depend on is impure and risks "Maximum recursive updates exceeded"; a
  // `watch` is the correct place for this kind of side effect.
  watch(
    flatNodes,
    (nodes) => {
      if (focusedId.value === null && nodes.length > 0) {
        focusedId.value = nodes[0]?.id ?? null
      }
    },
    { immediate: true },
  )

  function tabIndexFor(nodeId: string): 0 | -1 {
    const activeId = focusedId.value ?? flatNodes.value[0]?.id ?? null
    return nodeId === activeId ? 0 : -1
  }

  function indexOf(nodeId: string): number {
    return flatNodes.value.findIndex((node) => node.id === nodeId)
  }

  function focusAt(index: number): void {
    const node = flatNodes.value[index]
    if (node) {
      focusedId.value = node.id
    }
  }

  function expandAllSiblingsOf(nodeId: string): void {
    const node = flatNodes.value.find((candidate) => candidate.id === nodeId)
    if (!node) return
    const siblingIds = flatNodes.value
      .filter((candidate) => candidate.parentId === node.parentId && candidate.hasChildren)
      .map((candidate) => candidate.id)
    const next = new Set(collapsedIds.value)
    for (const siblingId of siblingIds) {
      next.delete(siblingId)
    }
    collapsedIds.value = next
  }

  function runTypeahead(character: string): void {
    if (typeaheadResetTimeoutId !== null) {
      clearTimeout(typeaheadResetTimeoutId)
    }
    typeaheadBuffer += character.toLowerCase()
    typeaheadResetTimeoutId = setTimeout(() => {
      typeaheadBuffer = ''
    }, 600)

    const currentIndex = focusedId.value ? indexOf(focusedId.value) : -1
    const nodes = flatNodes.value
    for (let offset = 1; offset <= nodes.length; offset += 1) {
      const candidate = nodes[(currentIndex + offset) % nodes.length]
      if (candidate && candidate.label.toLowerCase().startsWith(typeaheadBuffer)) {
        focusedId.value = candidate.id
        return
      }
    }
  }

  function onKeydown(event: KeyboardEvent, nodeId: string): void {
    const currentIndex = indexOf(nodeId)
    if (currentIndex === -1) return
    const node = flatNodes.value[currentIndex]
    if (!node) return

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        focusAt(Math.min(currentIndex + 1, flatNodes.value.length - 1))
        break
      case 'ArrowUp':
        event.preventDefault()
        focusAt(Math.max(currentIndex - 1, 0))
        break
      case 'ArrowRight':
        event.preventDefault()
        if (node.hasChildren && !node.expanded) {
          toggleExpanded(node.id)
        } else if (node.hasChildren && node.expanded) {
          focusAt(currentIndex + 1)
        }
        break
      case 'ArrowLeft':
        event.preventDefault()
        if (node.hasChildren && node.expanded) {
          toggleExpanded(node.id)
        } else if (node.parentId !== null) {
          focusedId.value = node.parentId
        }
        break
      case 'Home':
        event.preventDefault()
        focusAt(0)
        break
      case 'End':
        event.preventDefault()
        focusAt(flatNodes.value.length - 1)
        break
      case '*':
        event.preventDefault()
        expandAllSiblingsOf(nodeId)
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        options.onActivate?.(nodeId)
        break
      default:
        // A held modifier changes the key's meaning entirely (Ctrl+F, browser
        // shortcuts, etc.) — never treat it as a type-ahead character.
        if (
          event.key.length === 1 &&
          /\S/.test(event.key) &&
          !event.ctrlKey &&
          !event.altKey &&
          !event.metaKey
        ) {
          runTypeahead(event.key)
        }
    }
  }

  // Live updates must never steal or destroy focus (architecture §9.4): when
  // the focused node's device is unplugged, focus moves to the nearest
  // surviving sibling, else the parent, else nothing (the tree container).
  // Vue's `watch` hands the callback both the new and the just-superseded
  // value of a computed source, so the old flatNodes list — including the
  // removed node's siblings — is still available here even though it has
  // already vanished from the live `flatNodes.value`.
  watch(flatNodes, (nextFlatNodes, previousFlatNodes) => {
    const focused = focusedId.value
    if (focused === null) {
      return
    }
    if (nextFlatNodes.some((node) => node.id === focused)) {
      return
    }
    const removedNode = previousFlatNodes?.find((node) => node.id === focused)
    if (!removedNode) {
      return
    }

    // Prefer a surviving sibling at the same level (the common case: one
    // device unplugged, its neighbours under the same hub remain).
    const survivingSibling = nextFlatNodes.find((node) => node.parentId === removedNode.parentId)

    // Otherwise walk up the *pre-removal* ancestor chain to the nearest
    // ancestor that is still present. Covers a hub unplugged along with all
    // of its children — the immediate parent is gone too, so naively
    // falling back to `nextFlatNodes[0]` could land focus on an unrelated
    // USB branch instead of the nearest surviving structure.
    const previousNodesById = new Map((previousFlatNodes ?? []).map((node) => [node.id, node]))
    let survivingAncestorId: string | null = null
    let candidateAncestorId: string | null = removedNode.parentId
    while (candidateAncestorId !== null && survivingAncestorId === null) {
      if (nextFlatNodes.some((node) => node.id === candidateAncestorId)) {
        survivingAncestorId = candidateAncestorId
      } else {
        candidateAncestorId = previousNodesById.get(candidateAncestorId)?.parentId ?? null
      }
    }

    const fallback = survivingSibling?.id ?? survivingAncestorId ?? nextFlatNodes[0]?.id ?? null
    focusedId.value = fallback
    options.onFocusRecovered?.(fallback)
  })

  return {
    flatNodes,
    focusedId,
    isExpanded,
    toggleExpanded,
    tabIndexFor,
    onKeydown,
  }
}
