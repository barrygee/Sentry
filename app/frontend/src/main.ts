import { authTokenPrompt } from './components/auth/authTokenPrompt.js'
import { configDialog } from './components/config/configDialog.js'
import { hotspotDialog } from './components/hotspot/hotspotDialog.js'
import { serialFlashDialog } from './components/serial/serialFlashDialog.js'
import { ref, setAttribute, setVisible } from './core/dom.js'
import { watchStore } from './core/observable.js'
import { configStore, openDialog as openConfigDialog } from './state/configStore.js'
import { hotspotStore, openDialog as openHotspotDialog } from './state/hotspotStore.js'
import { openSdrsStream } from './stream/sdrsStream.js'
import { mountSdrsView } from './views/sdrsView.js'

/**
 * Application entry point.
 *
 * The shell — header, nav rail, headings, live regions — is already in
 * `index.html` and is never rebuilt. This wires behaviour to it: the rail
 * toggle, the two header buttons, the always-mounted dialogs, the device view,
 * and the SSE stream that feeds everything.
 */

const shell = document.body

// ---------------------------------------------------------------------------
// Nav rail show/hide
// ---------------------------------------------------------------------------
// The rail's visibility lives here rather than with the rail itself, because
// the control that flips it has to outlive the thing it hides: hiding the whole
// rail would otherwise take the button with it and leave no way back.
//
// `display:none` rather than removal, so the toggle's `aria-controls` keeps
// pointing at an element that exists even while the rail is hidden.
const navRail = ref(shell, 'nav-rail', HTMLElement)
const navRailToggle = ref(shell, 'nav-rail-toggle', HTMLButtonElement)

let isRailVisible = true

function applyRailVisibility(): void {
  setVisible(navRail, isRailVisible)
  setAttribute(navRailToggle, 'aria-expanded', isRailVisible)
  const label = isRailVisible ? 'Hide sidebar' : 'Show sidebar'
  setAttribute(navRailToggle, 'aria-label', label)
  setAttribute(navRailToggle, 'title', label)
  // The toggle carries the rail's own dark fill only while the rail is shown.
  // Once it is hidden the glyph sits directly on the light page canvas, where a
  // white mark would disappear — so it inverts to ink (4.2:1 at this opacity,
  // clearing the 3:1 a non-text mark needs).
  navRailToggle.classList.toggle('bg-ground-rail', isRailVisible)
  navRailToggle.classList.toggle('text-ink-inverse', isRailVisible)
  navRailToggle.classList.toggle('text-ink-primary', !isRailVisible)
}

navRailToggle.addEventListener('click', () => {
  isRailVisible = !isRailVisible
  applyRailVisibility()
})
applyRailVisibility()

// ---------------------------------------------------------------------------
// Header controls
// ---------------------------------------------------------------------------
// Each opens a modal, so each mirrors its dialog's open state into
// `aria-expanded` — without it the dialog appears with no indication of what
// produced it.
const hotspotButton = ref(shell, 'hotspot-settings-button', HTMLButtonElement)
const configButton = ref(shell, 'config-settings-button', HTMLButtonElement)

hotspotButton.addEventListener('click', () => {
  openHotspotDialog()
})
configButton.addEventListener('click', () => {
  openConfigDialog()
})

watchStore(hotspotStore, (state) => {
  setAttribute(hotspotButton, 'aria-expanded', state.dialogOpen)
})
watchStore(configStore, (state) => {
  setAttribute(configButton, 'aria-expanded', state.dialogOpen)
})

// ---------------------------------------------------------------------------
// Overlays
// ---------------------------------------------------------------------------
// Each of these mounts itself onto `document.body` when it opens (what
// `<Teleport to="body">` used to buy), so they are constructed once here and
// never appended.
hotspotDialog()
configDialog()
serialFlashDialog()
authTokenPrompt()

// ---------------------------------------------------------------------------
// The view, and the stream that feeds it
// ---------------------------------------------------------------------------
mountSdrsView(shell)
openSdrsStream()
