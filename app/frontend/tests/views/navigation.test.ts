import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createNavigation, type Destination } from '../../src/views/navigation.js'

/**
 * Tests for swapping between the console's two destinations.
 *
 * Three of these guard things that are invisible when broken, which is why they
 * are worth writing down:
 *
 * * focus moving to the new destination's heading — without it a screen-reader
 *   user activates a rail button and is told nothing happened;
 * * `aria-current` rather than `aria-expanded` — the buttons navigate now, and
 *   `aria-expanded` would promise something opening in place;
 * * the departure guard, which replaced a modal that could refuse to close.
 *   The hotspot's confirmation countdown relies on it: leaving mid-countdown
 *   abandons a network change already applied to the hardware.
 */

function buildShell(): {
  devicesView: HTMLElement
  settingsView: HTMLElement
  devicesButton: HTMLButtonElement
  settingsButton: HTMLButtonElement
  devicesHeading: HTMLElement
  settingsHeading: HTMLElement
} {
  document.body.innerHTML = `
    <button data-ref="nav-devices" type="button"></button>
    <button data-ref="nav-settings" type="button"></button>
    <div data-ref="devices-view"><h2 tabindex="-1" data-ref="devices-heading">Devices</h2></div>
    <div data-ref="settings-view" hidden><h2 tabindex="-1" data-ref="settings-heading">Settings</h2></div>
  `
  const query = <ElementType extends Element>(name: string): ElementType =>
    document.querySelector(`[data-ref="${name}"]`) as ElementType

  return {
    devicesView: query<HTMLElement>('devices-view'),
    settingsView: query<HTMLElement>('settings-view'),
    devicesButton: query<HTMLButtonElement>('nav-devices'),
    settingsButton: query<HTMLButtonElement>('nav-settings'),
    devicesHeading: query<HTMLElement>('devices-heading'),
    settingsHeading: query<HTMLElement>('settings-heading'),
  }
}

type Shell = ReturnType<typeof buildShell>

function navigationFor(
  shell: Shell,
  extras: {
    blockDeparture?: (from: Destination) => string | null
    announce?: (message: string) => void
    onSettingsShown?: () => void
    onSettingsHidden?: () => void
  } = {},
) {
  return createNavigation({
    devices: {
      view: shell.devicesView,
      navButton: shell.devicesButton,
      heading: shell.devicesHeading,
    },
    settings: {
      view: shell.settingsView,
      navButton: shell.settingsButton,
      heading: shell.settingsHeading,
      ...(extras.onSettingsShown ? { onShown: extras.onSettingsShown } : {}),
      ...(extras.onSettingsHidden ? { onHidden: extras.onSettingsHidden } : {}),
    },
    ...(extras.blockDeparture ? { blockDeparture: extras.blockDeparture } : {}),
    ...(extras.announce ? { announce: extras.announce } : {}),
  })
}

let shell: Shell

beforeEach(() => {
  shell = buildShell()
})

describe('createNavigation', () => {
  it('starts on devices, with settings hidden', () => {
    const navigation = navigationFor(shell)

    expect(navigation.current()).toBe('devices')
    expect(shell.devicesView.hidden).toBe(false)
    expect(shell.settingsView.hidden).toBe(true)
  })

  it('does not steal focus on the initial paint', () => {
    navigationFor(shell)

    expect(document.activeElement).toBe(document.body)
  })

  it('swaps the visible view when a rail button is pressed', () => {
    const navigation = navigationFor(shell)

    shell.settingsButton.click()

    expect(navigation.current()).toBe('settings')
    expect(shell.settingsView.hidden).toBe(false)
    expect(shell.devicesView.hidden).toBe(true)
  })

  it('moves focus to the arriving destination’s heading', () => {
    navigationFor(shell)

    shell.settingsButton.click()

    expect(document.activeElement).toBe(shell.settingsHeading)
  })

  it('marks the active button with aria-current and clears the other', () => {
    navigationFor(shell)

    shell.settingsButton.click()

    expect(shell.settingsButton.getAttribute('aria-current')).toBe('page')
    expect(shell.devicesButton.getAttribute('aria-current')).toBeNull()
  })

  it('never sets aria-expanded — these navigate, they do not disclose', () => {
    navigationFor(shell)

    shell.settingsButton.click()

    expect(shell.settingsButton.hasAttribute('aria-expanded')).toBe(false)
    expect(shell.devicesButton.hasAttribute('aria-expanded')).toBe(false)
  })

  it('calls onShown every time a destination becomes active, not just the first', () => {
    const onSettingsShown = vi.fn()
    navigationFor(shell, { onSettingsShown })

    shell.settingsButton.click()
    shell.devicesButton.click()
    shell.settingsButton.click()

    // Refetch-on-arrival: the hotspot can change from Sentinel, or roll itself
    // back, while nobody is looking at this screen.
    expect(onSettingsShown).toHaveBeenCalledTimes(2)
  })

  it('ignores a press on the destination already showing', () => {
    const onSettingsShown = vi.fn()
    navigationFor(shell, { onSettingsShown })

    shell.devicesButton.click()

    expect(onSettingsShown).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(document.body)
  })

  it('refuses a departure the guard blocks, and announces why', () => {
    const announce = vi.fn()
    const navigation = navigationFor(shell, {
      blockDeparture: (from) => (from === 'settings' ? 'Confirm the hotspot change first.' : null),
      announce,
    })

    shell.settingsButton.click()
    shell.devicesButton.click()

    expect(navigation.current()).toBe('settings')
    expect(shell.settingsView.hidden).toBe(false)
    expect(announce).toHaveBeenCalledWith('Confirm the hotspot change first.')
  })

  it('allows the departure once the guard stops blocking', () => {
    let blocked = true
    const navigation = navigationFor(shell, {
      // Only blocks leaving settings, as the real guard does. A guard that
      // blocked every departure would also block the trip *into* settings,
      // which is how the first draft of this test managed to pass its own
      // premise by accident.
      blockDeparture: (from) => (from === 'settings' && blocked ? 'Not yet.' : null),
    })

    shell.settingsButton.click()
    shell.devicesButton.click()
    expect(navigation.current()).toBe('settings')

    blocked = false
    shell.devicesButton.click()

    expect(navigation.current()).toBe('devices')
  })

  it('calls onHidden when a destination stops being active', () => {
    // This is where a staged import file and a stale error get discarded — the
    // work a dialog's close handler used to do. Losing it on the move to
    // sections would leave a file primed to apply, chosen for reasons the
    // operator no longer remembers.
    const onSettingsHidden = vi.fn()
    navigationFor(shell, { onSettingsHidden })

    shell.settingsButton.click()
    expect(onSettingsHidden).not.toHaveBeenCalled()

    shell.devicesButton.click()

    expect(onSettingsHidden).toHaveBeenCalledTimes(1)
  })

  it('does not call onHidden when the guard refuses the departure', () => {
    // Half-leaving would discard the operator's staged work while keeping them
    // on the screen that shows it.
    const onSettingsHidden = vi.fn()
    navigationFor(shell, {
      onSettingsHidden,
      blockDeparture: (from) => (from === 'settings' ? 'Not yet.' : null),
    })

    shell.settingsButton.click()
    shell.devicesButton.click()

    expect(onSettingsHidden).not.toHaveBeenCalled()
  })

  it('does not call onHidden on the initial paint', () => {
    const onSettingsHidden = vi.fn()
    navigationFor(shell, { onSettingsHidden })

    expect(onSettingsHidden).not.toHaveBeenCalled()
  })

  it('stops responding to the rail once destroyed', () => {
    const navigation = navigationFor(shell)

    navigation.destroy()
    shell.settingsButton.click()

    expect(navigation.current()).toBe('devices')
  })
})
