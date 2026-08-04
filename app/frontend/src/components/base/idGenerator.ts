/**
 * A tiny monotonic id generator, standing in for Vue's `useId()`. Used by
 * `BaseField` and `BaseSelect` to mint a unique id for their `<label for>`
 * pairing and `aria-describedby` wiring without any framework-level id
 * allocator.
 */
let nextId = 0

/** Returns a fresh id of the form `${prefix}-${n}`, unique for the page's lifetime. */
export function nextElementId(prefix: string): string {
  nextId += 1
  return `${prefix}-${nextId}`
}
