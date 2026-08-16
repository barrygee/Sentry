import type { Component } from '../../core/component.js'
import { rollbackCountdown } from '../base/rollbackCountdown.js'
import type { RollbackCountdownProps } from '../base/rollbackCountdown.js'

/**
 * The hotspot's commit-confirm window — the hotspot's wording over the shared
 * countdown.
 *
 * The timer, the announcement checkpoints and the deadline handling all live in
 * `base/rollbackCountdown`, because the wired share (ADR-0014) runs the
 * identical commit-confirm flow. This module supplies only what is specific to
 * a hotspot: the SSID as the subject, and "hotspot" as the noun the buttons and
 * announcements use.
 */
export interface HotspotConfirmCountdownProps {
  /** The network's name, so the notice names what is running. */
  ssid: string | null
  /** Unix ms by which confirmation must arrive. */
  deadlineMs: number
  busy?: boolean
  onConfirm: () => void
  onDiscard: () => void
  /**
   * Fires once when the deadline passes with no confirmation.
   *
   * The rollback happens on the server, silently — nothing is pushed to say it
   * has. Without this the countdown simply reached zero and the panel went on
   * showing the hotspot as up, long after it had been reverted, which is the
   * one state this whole flow exists to make visible.
   */
  onDeadlinePassed: () => void
}

function toCountdownProps(props: HotspotConfirmCountdownProps): RollbackCountdownProps {
  return {
    subjectName: props.ssid,
    subjectFallbackName: 'The hotspot',
    subjectNoun: 'hotspot',
    deadlineMs: props.deadlineMs,
    // Spread rather than assigned: under `exactOptionalPropertyTypes` an
    // explicit `busy: undefined` is not the same as an absent `busy`, and only
    // the latter lets the base component apply its own default.
    ...(props.busy === undefined ? {} : { busy: props.busy }),
    onConfirm: props.onConfirm,
    onDiscard: props.onDiscard,
    onDeadlinePassed: props.onDeadlinePassed,
  }
}

/** Builds a `HotspotConfirmCountdown`. `update` mutates the same notice in place. */
export function hotspotConfirmCountdown(
  props: HotspotConfirmCountdownProps,
): Component<HotspotConfirmCountdownProps> {
  const countdown = rollbackCountdown(toCountdownProps(props))

  return {
    element: countdown.element,

    update(nextProps): void {
      countdown.update(toCountdownProps(nextProps))
    },

    destroy(): void {
      countdown.destroy()
    },
  }
}
