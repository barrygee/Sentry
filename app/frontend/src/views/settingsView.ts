import { consolePasswordPanel } from '../components/auth/consolePasswordPanel.js'
import { configPanel } from '../components/config/configPanel.js'
import { hotspotPanel } from '../components/hotspot/hotspotPanel.js'
import type { Component } from '../core/component.js'
import { ref } from '../core/dom.js'
import { loadPreview, resetTransientState as resetConfig } from '../state/configStore.js'
import {
  refresh as refreshHotspot,
  resetTransientState as resetHotspot,
} from '../state/hotspotStore.js'

/**
 * The Settings destination: the two instance-wide surfaces, as sections.
 *
 * Both were modals reached from header icons. A modal is the wrong shape for
 * either — they are long, mostly read rather than acted on, and the hotspot's
 * confirmation countdown wants to stay visible while an operator walks off to
 * check whether their WiFi still works. Neither is per-device, so neither
 * belongs to a card.
 *
 * Per-device confirmations (serial flash, forget) stay modals. They interrupt
 * one card's work and must be answered before it continues, which is what a
 * modal is actually for.
 *
 * Data is fetched when the view is shown rather than at construction. The
 * hotspot can be changed from Sentinel or rolled back by its own countdown
 * while nobody is looking, so a panel mounted at boot and never refreshed
 * would show a state that stopped being true minutes ago.
 */
export function mountSettingsView(root: ParentNode): {
  onShown: () => void
  onHidden: () => void
  focusPasswordField: () => void
  destroy: () => void
} {
  const passwordContainer = ref(root, 'console-password-panel', HTMLElement)
  const hotspotContainer = ref(root, 'hotspot-panel', HTMLElement)
  const configContainer = ref(root, 'config-panel', HTMLElement)

  const panels: Component<void>[] = []

  // First: it protects everything below it, and on an open console it is the
  // thing an operator arriving at Settings most needs to see.
  const password = consolePasswordPanel()
  passwordContainer.appendChild(password.element)
  panels.push(password)

  const hotspot = hotspotPanel()
  hotspotContainer.appendChild(hotspot.element)
  panels.push(hotspot)

  const config = configPanel()
  configContainer.appendChild(config.element)
  panels.push(config)

  return {
    /**
     * Refetch both panels' data. Called every time Settings becomes the active
     * destination, which is the section equivalent of the refresh the dialogs
     * did on open.
     */
    onShown(): void {
      void refreshHotspot()
      void loadPreview()
    },

    /**
     * Drop what should not outlive a visit: a staged import file, and any error
     * from a previous attempt. The dialogs did this on close; leaving the
     * screen is the equivalent moment.
     */
    onHidden(): void {
      resetHotspot()
      resetConfig()
    },

    /** Focus the new-password box, for an operator sent here to set one. */
    focusPasswordField(): void {
      password.focusPasswordField()
    },

    destroy(): void {
      for (const panel of panels) {
        panel.destroy()
      }
    },
  }
}
