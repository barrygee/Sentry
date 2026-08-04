import type { Component } from '../../core/component.js'
import type { DeviceStatus } from '../../api/client.js'
import { baseToggle } from '../base/baseToggle.js'

/**
 * Whether this device is withheld from Sentinel: switched on keeps it out of
 * `GET /api/v1/sdrs` entirely, switched off publishes it there.
 *
 * This is what lets one Sentry run more dongles than it shares — four
 * configured devices with two of them marked private, and a Sentinel querying
 * the export sees exactly the other two.
 *
 * **On the caption.** The label is the stable state word "Private", not an
 * action ("Make private"), because `role="switch"` already announces on/off:
 * an action label makes a screen reader say "Make private, switch, on", which
 * reads as though the *action* is on. "Private, switch, on" says what is true.
 * The visible caption also stays put while the switch moves, which is what
 * makes the two states distinguishable at a glance down a column of cards.
 */
export interface DeviceVisibilityToggleProps {
  device: DeviceStatus
  onCommit: (visibility: 'public' | 'private') => void
}

function accessibleNameFor(device: DeviceStatus): string {
  return `Private — keep ${device.name || device.device_id} out of the Sentinel SDR export`
}

/** Builds a `DeviceVisibilityToggle`. `update` mutates the same switch in place. */
export function deviceVisibilityToggle(
  props: DeviceVisibilityToggleProps,
): Component<DeviceVisibilityToggleProps> {
  let currentProps = props

  function commitVisibility(nextIsPrivate: boolean): void {
    currentProps.onCommit(nextIsPrivate ? 'private' : 'public')
  }

  const toggle = baseToggle({
    value: props.device.visibility === 'private',
    onChange: commitVisibility,
    label: 'Private',
    accessibleName: accessibleNameFor(props.device),
  })

  return {
    element: toggle.element,

    update(nextProps): void {
      currentProps = nextProps
      toggle.update({
        value: nextProps.device.visibility === 'private',
        onChange: commitVisibility,
        label: 'Private',
        accessibleName: accessibleNameFor(nextProps.device),
      })
    },

    destroy(): void {
      toggle.destroy()
    },
  }
}
