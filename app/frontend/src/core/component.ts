/**
 * The component contract.
 *
 * A component is a factory that builds its DOM once and then mutates it in
 * place. That is the whole reason this app does not re-render: several of its
 * fields are edited inline (device name, port, notes, antenna), and replacing a
 * subtree while the operator is typing would move focus and drop the caret.
 *
 * Each factory returns a handle:
 *   * `element`  — the root node, appended by the parent.
 *   * `update`   — called with fresh props whenever state changes. Must be
 *                  idempotent: it will be called with unchanged props.
 *   * `destroy`  — releases subscriptions, timers and child components. Called
 *                  by `keyedList` when an item leaves, and by dialogs on close.
 */
export interface Component<Props = void> {
  readonly element: HTMLElement
  update(props: Props): void
  destroy(): void
}

/** A component factory: builds from initial props, returns the handle. */
export type ComponentFactory<Props> = (props: Props) => Component<Props>

/**
 * Keeps a container's children in sync with a keyed list of props, creating,
 * updating, reordering and destroying child components as the list changes.
 *
 * Keying by a stable identity (device id, serial, notice id) is what lets a
 * device card survive a status refresh with its half-typed name intact.
 */
export function keyedList<Props, Key extends string>(
  container: Element,
  factory: ComponentFactory<Props>,
  keyOf: (props: Props) => Key,
): {
  update(items: Props[]): void
  destroy(): void
} {
  const mounted = new Map<Key, Component<Props>>()

  return {
    update(items: Props[]): void {
      const seen = new Set<Key>()

      items.forEach((props, index) => {
        const key = keyOf(props)
        seen.add(key)

        let child = mounted.get(key)
        if (child) {
          child.update(props)
        } else {
          child = factory(props)
          mounted.set(key, child)
        }

        // Move into position only when it is not already there — an
        // unconditional `insertBefore` would detach and reattach the node,
        // which blurs whatever inside it had focus.
        const currentAtIndex = container.children[index]
        if (currentAtIndex !== child.element) {
          container.insertBefore(child.element, currentAtIndex ?? null)
        }
      })

      for (const [key, child] of mounted) {
        if (!seen.has(key)) {
          child.destroy()
          child.element.remove()
          mounted.delete(key)
        }
      }
    },

    destroy(): void {
      for (const child of mounted.values()) {
        child.destroy()
        child.element.remove()
      }
      mounted.clear()
    },
  }
}

/**
 * Renders at most one child into a container, swapping it when the chosen
 * factory changes — the equivalent of a `v-if` / `v-else-if` chain.
 *
 * `choose` returns the factory to use, or `null` for "render nothing". Passing
 * the same factory twice updates in place rather than rebuilding.
 */
export function switchChild<Props>(container: Element): {
  update(factory: ComponentFactory<Props> | null, props: Props): void
  destroy(): void
} {
  let currentFactory: ComponentFactory<Props> | null = null
  let current: Component<Props> | null = null

  return {
    update(factory: ComponentFactory<Props> | null, props: Props): void {
      if (factory === currentFactory) {
        current?.update(props)
        return
      }

      current?.destroy()
      current?.element.remove()
      current = null
      currentFactory = factory

      if (factory) {
        current = factory(props)
        container.appendChild(current.element)
      }
    },

    destroy(): void {
      current?.destroy()
      current?.element.remove()
      current = null
      currentFactory = null
    },
  }
}
