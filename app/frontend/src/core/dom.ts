/**
 * Element construction helpers.
 *
 * These replace Vue's template compiler. They are deliberately thin: `el` is a
 * typed `document.createElement` with attributes, listeners and children folded
 * into one call, so a component's markup still reads top-to-bottom in roughly
 * the shape the retired `.vue` template had.
 *
 * There is no virtual DOM and no diffing. Components own their nodes and mutate
 * them in place (see `component.ts`), because this console edits device names,
 * ports and notes inline — a re-render that replaced the subtree would blow away
 * the caret mid-keystroke.
 */

/** Anything accepted as a child: nodes, text, or nothing (for conditional slots). */
export type Child = Node | string | number | null | undefined | false

type EventMap = HTMLElementEventMap

/** Listener map, keyed by DOM event name. Attached with `addEventListener`. */
export type Listeners = {
  [EventName in keyof EventMap]?: (event: EventMap[EventName]) => void
}

export interface ElementOptions {
  /**
   * Attributes, set with `setAttribute`. `null`/`undefined`/`false` omit the
   * attribute entirely rather than writing the string "false" — which matters
   * for ARIA state, where a literal `aria-hidden="false"` is not the same thing
   * as an absent one.
   */
  attrs?: Record<string, string | number | boolean | null | undefined>
  /** Space-separated class list. Falsy entries are dropped, so conditionals inline cleanly. */
  class?: (string | false | null | undefined)[] | string
  /** DOM event listeners. */
  on?: Listeners
  /** Properties assigned directly — `value`, `checked`, `disabled` and friends. */
  props?: Record<string, unknown>
}

/** Joins a class list, dropping falsy entries so conditionals can be written inline. */
export function classes(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}

function appendChild(parent: Node, child: Child): void {
  if (child === null || child === undefined || child === false) {
    return
  }
  parent.appendChild(
    typeof child === 'string' || typeof child === 'number'
      ? document.createTextNode(String(child))
      : child,
  )
}

/** Creates an element, applying attributes, classes, listeners, properties and children. */
export function el<TagName extends keyof HTMLElementTagNameMap>(
  tag: TagName,
  options: ElementOptions = {},
  children: Child[] = [],
): HTMLElementTagNameMap[TagName] {
  const element = document.createElement(tag)

  if (options.class !== undefined) {
    const className = Array.isArray(options.class) ? classes(...options.class) : options.class
    if (className) {
      element.className = className
    }
  }

  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    setAttribute(element, name, value)
  }

  for (const [name, value] of Object.entries(options.props ?? {})) {
    Reflect.set(element, name, value)
  }

  for (const [eventName, listener] of Object.entries(options.on ?? {})) {
    element.addEventListener(eventName, listener as EventListener)
  }

  for (const child of children) {
    appendChild(element, child)
  }

  return element
}

/**
 * Sets or removes one attribute. Exported because components toggling ARIA state
 * in place need exactly this null-means-remove behaviour that `el` applies at
 * construction.
 */
export function setAttribute(
  element: Element,
  name: string,
  value: string | number | boolean | null | undefined,
): void {
  if (value === null || value === undefined || value === false) {
    element.removeAttribute(name)
    return
  }
  element.setAttribute(name, value === true ? '' : String(value))
}

/** Replaces an element's children in one pass. */
export function replaceChildren(parent: Element, ...children: Child[]): void {
  parent.replaceChildren()
  for (const child of children) {
    appendChild(parent, child)
  }
}

/** Sets `textContent` only when it actually differs, so the browser skips needless layout. */
export function setText(element: Element, text: string): void {
  if (element.textContent !== text) {
    element.textContent = text
  }
}

/**
 * Shows or hides an element without removing it from the DOM — the equivalent of
 * Vue's `v-show`. Used where a hidden element must still be referenceable, as
 * the nav rail is by its toggle's `aria-controls`.
 */
export function setVisible(element: HTMLElement, visible: boolean): void {
  element.style.display = visible ? '' : 'none'
}

/**
 * Clones the content of a `<template>` declared in `index.html`.
 *
 * Markup that is large, static and mostly structural stays in the HTML where it
 * reads as markup; only the parts that vary are built with `el`.
 */
export function cloneTemplate(templateId: string): DocumentFragment {
  const template = document.getElementById(templateId)
  if (!(template instanceof HTMLTemplateElement)) {
    throw new Error(`No <template> with id "${templateId}"`)
  }
  return template.content.cloneNode(true) as DocumentFragment
}

/**
 * Looks up a required descendant by `data-ref`, narrowed to the expected type.
 *
 * Templates mark their moving parts with `data-ref="…"`; this is how a component
 * grabs them once at construction rather than re-querying on every update.
 */
export function ref<ElementType extends Element>(
  root: ParentNode,
  name: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- a constructor's static side is not expressible without it
  expected: abstract new (...args: any[]) => ElementType,
): ElementType {
  const found = root.querySelector(`[data-ref="${name}"]`)
  if (!(found instanceof expected)) {
    throw new Error(`Expected [data-ref="${name}"] to be a ${expected.name}`)
  }
  return found
}
