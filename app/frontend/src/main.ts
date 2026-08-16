import { signInView } from './components/auth/signInView.js'
import { logoMark } from './components/base/logoMark.js'
import { unprotectedWarning } from './components/auth/unprotectedWarning.js'
import { liveAnnouncer } from './core/liveAnnouncer.js'
import { watchStore } from './core/observable.js'
import { ref, setAttribute, setVisible } from './core/dom.js'
import { onUnauthorized } from './api/client.js'
import {
  consoleAuthStore,
  markUnauthenticated,
  mustSignIn,
  refreshAuthState,
  signOut,
} from './state/consoleAuth.js'
import { hotspotStore, isAwaitingConfirmation } from './state/hotspotStore.js'
import {
  isAwaitingConfirmation as isAwaitingWiredConfirmation,
  wiredStore,
} from './state/wiredStore.js'
import { openSdrsStream } from './stream/sdrsStream.js'
import { mountSdrsView } from './views/sdrsView.js'
import { createNavigation } from './views/navigation.js'
import { mountSettingsView } from './views/settingsView.js'

/**
 * Application entry point.
 *
 * The shell — header, nav rail, headings, live regions — is already in
 * `index.html` and is never rebuilt. This wires behaviour to it: the rail
 * toggle, navigation between the two destinations, the per-device dialogs, the
 * views, and the SSE stream that feeds everything.
 */

const shell = document.body

// The header's ⊙ mark. Drawn here rather than inline in `index.html` because
// the sign-in screen shows the same mark, and a hand-copied second SVG is how
// an app ends up with two slightly different logos.
ref(shell, 'header-logo-mark', HTMLElement).appendChild(logoMark({ size: 26 }))

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
// ---------------------------------------------------------------------------
// The views, and the stream that feeds them
// ---------------------------------------------------------------------------
mountSdrsView(shell)
const settingsView = mountSettingsView(shell)

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const navigation = createNavigation({
  devices: {
    view: ref(shell, 'devices-view', HTMLElement),
    navButton: ref(shell, 'nav-devices', HTMLButtonElement),
    heading: ref(shell, 'devices-heading-anchor', HTMLElement),
  },
  settings: {
    view: ref(shell, 'settings-view', HTMLElement),
    navButton: ref(shell, 'nav-settings', HTMLButtonElement),
    heading: ref(shell, 'settings-heading-anchor', HTMLElement),
    onShown: () => settingsView.onShown(),
    onHidden: () => settingsView.onHidden(),
  },
  // Leaving mid-countdown abandons a network change already applied to the
  // hardware; the rollback would then strand an operator who walked away
  // believing it had stuck. The modal used to prevent this by refusing to
  // close, which a section cannot do.
  blockDeparture: (from) => {
    if (from !== 'settings') return null
    if (isAwaitingConfirmation(hotspotStore.state)) {
      return 'Confirm or discard the hotspot change before leaving settings.'
    }
    // Wired sharing runs the same commit-confirm flow (ADR-0014) and needs the
    // same guard: walking away mid-countdown abandons a change that has already
    // taken the Pi's Ethernet port off the LAN.
    if (isAwaitingWiredConfirmation(wiredStore.state)) {
      return 'Confirm or discard the wired-sharing change before leaving settings.'
    }
    return null
  },
  announce: (message) => liveAnnouncer().announceAssertive(message),
})

// ---------------------------------------------------------------------------
// Authentication (ADR-0010)
// ---------------------------------------------------------------------------
// Any 401 raises the sign-in screen. Registered rather than imported by the API
// client, which the auth store already depends on.
onUnauthorized(markUnauthenticated)

const signInRoot = ref(shell, 'sign-in-root', HTMLElement)
const signIn = signInView()
signInRoot.appendChild(signIn.element)

const unprotectedWarningContainer = ref(shell, 'unprotected-warning', HTMLElement)
unprotectedWarningContainer.appendChild(
  unprotectedWarning({
    // Take the operator to the field rather than raising a dialog over the
    // devices view. The password lives in Settings, which is now a real
    // destination — a modal here would put the same control in two places and
    // leave whoever used it unsure where to find it again.
    onSetPassword: () => {
      navigation.go('settings')
      settingsView.focusPasswordField()
    },
  }).element,
)

// The shell and the sign-in screen are mutually exclusive. Hiding the shell
// rather than dimming it is deliberate: every management route answers 401 in
// this state, so a console visible behind the form would be showing stale data
// it can no longer refresh.
const appShell = ref(shell, 'app-shell', HTMLElement)

// Sign out lives in the header band, beside the wordmark, rather than inside
// the password card: it ends a session, which is a property of the whole
// console, not of the setting that happens to have created one.
const headerSignOut = ref(shell, 'header-sign-out', HTMLButtonElement)
headerSignOut.addEventListener('click', () => void signOut())

watchStore(consoleAuthStore, (state) => {
  // Neither, until the server has said which. The store assumes
  // `authenticated: true` so that an *open* console never flashes a login form
  // it would immediately take away — but that assumption showed the whole
  // console for a moment on a protected one, which is the worse half of the
  // same trade: it shows data to someone who has not signed in yet.
  //
  // A blank page for that moment is the honest answer. It lasts one request,
  // and the alternative is always wrong for one of the two kinds of console.
  const decided = state.phase !== 'loading'
  const signingIn = mustSignIn(state)
  setVisible(appShell, decided && !signingIn)
  setVisible(signInRoot, decided && signingIn)
  // Nothing to sign out of on an open console.
  setVisible(headerSignOut, state.passwordSet)
})

void refreshAuthState()

openSdrsStream()
