/**
 * A minimal SVG element builder, alongside `core/dom.ts`'s `el`.
 *
 * `el` creates elements with `document.createElement`, which is correct for
 * HTML but mints a namespace-less `HTMLUnknownElement` for tags like `svg` and
 * `path` — the browser never renders it. SVG needs `document.createElementNS`
 * with the SVG namespace instead, which is the one thing this helper adds.
 */
export interface SvgElementOptions {
  /** Attributes, set with `setAttribute` — plain strings/numbers only; SVG has no boolean attributes here. */
  attrs?: Record<string, string | number>
  /** Space-separated class list. */
  class?: string
}

export function svgEl<TagName extends keyof SVGElementTagNameMap>(
  tag: TagName,
  options: SvgElementOptions = {},
  children: SVGElement[] = [],
): SVGElementTagNameMap[TagName] {
  const element = document.createElementNS(
    'http://www.w3.org/2000/svg',
    tag,
  ) as SVGElementTagNameMap[TagName]

  if (options.class !== undefined) {
    element.setAttribute('class', options.class)
  }

  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    element.setAttribute(name, String(value))
  }

  for (const child of children) {
    element.appendChild(child)
  }

  return element
}
