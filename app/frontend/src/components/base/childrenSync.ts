import type { Child } from '../../core/dom.js'

/**
 * Syncs a container's children to a fresh list of nodes/strings without
 * removing and reinserting a node that is already in the right place.
 *
 * Several base components (`BaseDialog`, `PanelStack`, `NoticeBox`, `DataCell`,
 * ...) accept a slot of arbitrary content and are handed a fresh `children`
 * array on every `update()`, even when nothing in it changed. `Element
 * .replaceChildren` would detach every existing node before reattaching it,
 * which blurs whatever inside the slot currently holds focus or a caret (a
 * dialog's own input, a device card mid-rename) — the exact regression
 * `component.ts` warns against. This only touches positions whose node
 * actually differs, matching the "move only if not already there" rule
 * `keyedList` uses for keyed components.
 */
export function syncChildren(container: Element, children: readonly Child[]): void {
  const desiredNodes: Node[] = []

  for (const child of children) {
    if (child === null || child === undefined || child === false) {
      continue
    }
    if (typeof child === 'string' || typeof child === 'number') {
      const text = String(child)
      const nodeAlreadyAtThisPosition = container.childNodes[desiredNodes.length]
      // Reuse the existing text node when it already holds this exact text,
      // rather than minting a new one that would have to be swapped in.
      desiredNodes.push(
        nodeAlreadyAtThisPosition instanceof Text && nodeAlreadyAtThisPosition.data === text
          ? nodeAlreadyAtThisPosition
          : document.createTextNode(text),
      )
    } else {
      desiredNodes.push(child)
    }
  }

  desiredNodes.forEach((node, index) => {
    const currentNodeAtIndex = container.childNodes[index]
    if (currentNodeAtIndex !== node) {
      container.insertBefore(node, currentNodeAtIndex ?? null)
    }
  })

  while (container.childNodes.length > desiredNodes.length) {
    container.lastChild?.remove()
  }
}
