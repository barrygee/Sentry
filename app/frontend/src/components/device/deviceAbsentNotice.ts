import { el, setText } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * The inline "this device isn't plugged in" note on a configured device's
 * card. Neutral-toned: an absent ghost is an expected state, not a fault, so
 * it gets the plain raised wash rather than a warning colour.
 */
export interface DeviceAbsentNoticeProps {
  lastTopologyPath?: string | null
}

function messageFor(lastTopologyPath: string | null | undefined): string {
  return lastTopologyPath
    ? `Device absent — was in USB port ${lastTopologyPath}.`
    : 'Device absent.'
}

/** Builds a `DeviceAbsentNotice`. `update` mutates the same paragraph in place. */
export function deviceAbsentNotice(
  props: DeviceAbsentNoticeProps,
): Component<DeviceAbsentNoticeProps> {
  const paragraph = el('p', { class: 'm-0' }, [messageFor(props.lastTopologyPath)])

  const box = noticeBox({ tone: 'neutral', children: [paragraph] })

  return {
    element: box.element,

    update(nextProps): void {
      setText(paragraph, messageFor(nextProps.lastTopologyPath))
    },

    destroy(): void {
      box.destroy()
    },
  }
}
