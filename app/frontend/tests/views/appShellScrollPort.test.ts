import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Guards the one class that keeps the app shell exactly one viewport tall.
 *
 * `main` is the scroll port: the shell is `h-full overflow-hidden` and the
 * content scrolls inside `main`, never the window. Every `sr-only` element is
 * `position: absolute`, and an absolutely positioned box is clipped by an
 * ancestor's `overflow` only when that ancestor is its *containing block* — a
 * `static` ancestor never is. With `main` left static, the visually-hidden
 * checkbox inside each toggle escaped the scroll port, grew
 * `documentElement.scrollHeight` past the viewport, and gave the window a
 * scrollbar. Focusing a toggle then scrolled the window to reveal it and slid
 * the shell off screen — header and rail gone, panel cut off, a band of empty
 * background below.
 *
 * **This is a structural pin, not a proof.** jsdom has no layout engine, so
 * document height and window scroll cannot be asserted here; the real
 * behaviour was verified in a browser. What this catches is the specific way
 * the bug arrives — someone tidying utility classes and dropping a `relative`
 * that reads like decoration. Asserting it next to `overflow-y-auto` is
 * deliberate: the two are only meaningful together.
 */

// `process.cwd()` rather than `import.meta.url`: Vitest's jsdom environment
// serves modules over an http URL, so `fileURLToPath` refuses them. The config
// pins `root` to this package, so the cwd is a stable base.
const indexHtml = readFileSync(resolve(process.cwd(), 'index.html'), 'utf-8')

function mainElementClasses(): string[] {
  // Narrowed with explicit throws rather than non-null assertions: under
  // `noUncheckedIndexedAccess` a capture group is `string | undefined`, and a
  // `!` here would trade a clear failure message for a TypeError.
  const openingTag = /<main\b[^>]*>/.exec(indexHtml)?.[0]
  if (openingTag === undefined) throw new Error('index.html contains no <main> element')

  const classList = /class="([^"]*)"/.exec(openingTag)?.[1]
  if (classList === undefined) throw new Error('<main> carries no class attribute')

  return classList.split(/\s+/).filter((className) => className !== '')
}

describe('the app shell scroll port', () => {
  it('makes main the containing block, so absolute sr-only children stay clipped', () => {
    expect(mainElementClasses()).toContain('relative')
  })

  it('still scrolls inside main rather than scrolling the window', () => {
    // The other half of the pair. If this ever stops being the scroll port,
    // `relative` stops being load-bearing and the test above stops meaning
    // anything — so a change to either must be a deliberate look at both.
    expect(mainElementClasses()).toContain('overflow-y-auto')
  })

  it('declares exactly one main element for the shell', () => {
    // Two scroll ports would mean the assertions above pin only the first,
    // silently leaving the second static.
    expect(indexHtml.match(/<main\b/g)).toHaveLength(1)
  })
})
