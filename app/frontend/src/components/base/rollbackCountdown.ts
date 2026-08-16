import { el, setText } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { liveAnnouncer } from '../../core/liveAnnouncer.js'
import { baseButton } from './baseButton.js'
import { noticeBox } from './noticeBox.js'

/**
 * The commit-confirm window: a network change that is live on trial and will
 * undo itself unless somebody confirms it from the other side.
 *
 * Shared by the WiFi hotspot and the wired share, which run the identical
 * commit-confirm flow against the identical rollback timer on the server. The
 * only differences are the words — what is on trial and what it is called — so
 * those arrive as props rather than as a second copy of the timer.
 *
 * The countdown is announced at 60, 30 and 10 seconds only, never per second.
 * A live region updated once a second is unusable with a screen reader — it
 * talks over everything else and the operator learns nothing they could not get
 * from three checkpoints. The deadline is also rendered as plain text, so the
 * information does not exist solely in a ticking number.
 *
 * No animated progress bar: there is nothing here that motion conveys and text
 * does not, which makes it the wrong place to spend a `prefers-reduced-motion`
 * exception.
 *
 * Owns a one-second interval timer — safety-critical, since it drives the
 * rollback deadline's announcements. `destroy` clears it; a leaked timer here
 * would keep announcing after the panel that hosted it is gone.
 */
export interface RollbackCountdownProps {
  /**
   * What is on trial, named — an SSID, an interface name.
   *
   * `null` falls back to `subjectFallbackName`, so the sentence still reads
   * when the thing has no name of its own to give.
   */
  subjectName: string | null
  /** Stands in for `subjectName` when it is null, e.g. "The hotspot". */
  subjectFallbackName: string
  /** The lowercase noun used in announcements and button names, e.g. "hotspot". */
  subjectNoun: string
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
   * showing the change as live, long after it had been reverted, which is the
   * one state this whole flow exists to make visible.
   */
  onDeadlinePassed: () => void
}

const ANNOUNCE_AT_SECONDS = [60, 30, 10]

function remainingSeconds(deadlineMs: number): number {
  return Math.max(0, Math.round((deadlineMs - Date.now()) / 1000))
}

function formatRemaining(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainingSecondsPart = seconds % 60
  return minutes > 0
    ? `${minutes}m ${String(remainingSecondsPart).padStart(2, '0')}s`
    : `${seconds}s`
}

/** Builds a `RollbackCountdown`. `update` mutates the same notice in place. */
export function rollbackCountdown(
  props: RollbackCountdownProps,
): Component<RollbackCountdownProps> {
  let currentProps = props
  let currentDeadlineMs = props.deadlineMs
  let secondsRemaining = remainingSeconds(props.deadlineMs)
  let deadlineReported = false
  const announcedThresholds = new Set<number>()

  const remainingSpan = el('span', { class: 'font-tabular' }, [])

  // The subject's own name leads, so the notice says which change is on trial
  // rather than restating the mechanism. Filled by `renderSubjectName` because
  // the name can change under an update.
  const subjectNameSpan = el('strong', { class: 'font-semibold' }, [])

  const messageParagraph = el('p', { class: 'm-0' }, [
    subjectNameSpan,
    ' is currently running. Sentry will undo the change and restore the previous connection in ',
    remainingSpan,
    ' unless you confirm.',
  ])

  function confirmAriaLabel(): string {
    return `Confirm this ${currentProps.subjectNoun}`
  }

  function discardAriaLabel(): string {
    return `Cancel this ${currentProps.subjectNoun} and restore the previous connection`
  }

  // "Confirm" and "Cancel", not "Keep this hotspot" / "Stop it now": the
  // sentence above already says what is running and what happens if nobody
  // acts, so the buttons only have to name the two answers to it.
  const confirmButton = baseButton({
    variant: 'on-bright',
    disabled: props.busy ?? false,
    onClick: () => currentProps.onConfirm(),
    // The visible label is short; the accessible name keeps the object of the
    // verb, since a screen reader user may meet the button out of context.
    ariaLabel: confirmAriaLabel(),
    children: ['Confirm'],
  })
  const discardButton = baseButton({
    variant: 'on-bright',
    disabled: props.busy ?? false,
    onClick: () => currentProps.onDiscard(),
    ariaLabel: discardAriaLabel(),
    children: ['Cancel'],
  })
  const buttonRow = el('div', { class: 'flex flex-wrap gap-2' }, [
    confirmButton.element,
    discardButton.element,
  ])

  const bodyWrapper = el('div', { class: 'flex flex-col gap-3' }, [messageParagraph, buttonRow])
  const notice = noticeBox({ tone: 'warn', role: 'status', children: [bodyWrapper] })

  function renderRemaining(): void {
    setText(remainingSpan, formatRemaining(secondsRemaining))
  }

  function renderSubjectName(): void {
    setText(subjectNameSpan, currentProps.subjectName ?? currentProps.subjectFallbackName)
  }

  function tick(): void {
    secondsRemaining = remainingSeconds(currentDeadlineMs)
    renderRemaining()
    for (const threshold of ANNOUNCE_AT_SECONDS) {
      if (secondsRemaining <= threshold && !announcedThresholds.has(threshold)) {
        announcedThresholds.add(threshold)
        liveAnnouncer().announcePolite(
          `${threshold} seconds left to confirm the ${currentProps.subjectNoun}, or it will be rolled back.`,
        )
      }
    }
    // Once per window, not once per tick: the state this asks for arrives
    // asynchronously, and the timer keeps running until the panel replaces
    // this component.
    if (secondsRemaining === 0 && !deadlineReported) {
      deadlineReported = true
      currentProps.onDeadlinePassed()
    }
  }

  const intervalId = setInterval(tick, 1000)

  renderRemaining()
  renderSubjectName()

  return {
    element: notice.element,

    update(nextProps): void {
      currentProps = nextProps
      renderSubjectName()
      // A new confirmation window is a new set of checkpoints.
      if (nextProps.deadlineMs !== currentDeadlineMs) {
        currentDeadlineMs = nextProps.deadlineMs
        deadlineReported = false
        announcedThresholds.clear()
        secondsRemaining = remainingSeconds(currentDeadlineMs)
        renderRemaining()
      }
      confirmButton.update({
        variant: 'on-bright',
        disabled: nextProps.busy ?? false,
        onClick: () => currentProps.onConfirm(),
        ariaLabel: confirmAriaLabel(),
        children: ['Confirm'],
      })
      discardButton.update({
        variant: 'on-bright',
        disabled: nextProps.busy ?? false,
        onClick: () => currentProps.onDiscard(),
        ariaLabel: discardAriaLabel(),
        children: ['Cancel'],
      })
    },

    destroy(): void {
      clearInterval(intervalId)
      confirmButton.destroy()
      discardButton.destroy()
      notice.destroy()
    },
  }
}
