import type { Component } from '../../core/component.js'
import { rollbackCountdown } from '../base/rollbackCountdown.js'
import type { RollbackCountdownProps } from '../base/rollbackCountdown.js'

/**
 * The wired share's commit-confirm window — the wired wording over the shared
 * countdown.
 *
 * The timer, the announcement checkpoints and the deadline handling live in
 * `base/rollbackCountdown`, shared with the hotspot, which runs the identical
 * flow. This module supplies only the subject: the shared port's name, and
 * "wired share" as the noun the buttons and announcements use.
 */
export interface WiredConfirmCountdownProps {
  /** The shared port's name, so the notice says which port is on trial. */
  interfaceName: string | null
  /** Unix ms by which confirmation must arrive. */
  deadlineMs: number
  busy?: boolean
  onConfirm: () => void
  onDiscard: () => void
  /**
   * Fires once when the deadline passes with no confirmation.
   *
   * The rollback happens on the server, silently — nothing is pushed to say it
   * has. Without this the countdown would reach zero and the panel go on
   * showing sharing as up, long after the port had been handed back to the LAN.
   */
  onDeadlinePassed: () => void
}

function toCountdownProps(props: WiredConfirmCountdownProps): RollbackCountdownProps {
  return {
    subjectName: props.interfaceName === null ? null : `Sharing on ${props.interfaceName}`,
    subjectFallbackName: 'Wired sharing',
    subjectNoun: 'wired share',
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

/** Builds a `WiredConfirmCountdown`. `update` mutates the same notice in place. */
export function wiredConfirmCountdown(
  props: WiredConfirmCountdownProps,
): Component<WiredConfirmCountdownProps> {
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
