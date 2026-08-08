import { el, setText } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { liveAnnouncer } from '../../core/liveAnnouncer.js'
import { baseButton } from '../base/baseButton.js'
import { noticeBox } from '../base/noticeBox.js'

/**
 * The commit-confirm window: a hotspot that is up on trial and will undo
 * itself unless somebody confirms it from the other side.
 *
 * The countdown is announced at 60, 30 and 10 seconds only, never per second.
 * A live region updated once a second is unusable with a screen reader — it
 * talks over everything else and the operator learns nothing they could not
 * get from three checkpoints. The deadline is also rendered as plain text, so
 * the information does not exist solely in a ticking number.
 *
 * No animated progress bar: there is nothing here that motion conveys and
 * text does not, which makes it the wrong place to spend a
 * `prefers-reduced-motion` exception.
 *
 * Owns a one-second interval timer — safety-critical, since it drives the
 * rollback deadline's announcements. `destroy` clears it; a leaked timer here
 * would keep announcing after the dialog that hosted it is gone.
 */
export interface HotspotConfirmCountdownProps {
  /** Unix ms by which confirmation must arrive. */
  deadlineMs: number
  busy?: boolean
  onConfirm: () => void
  onDiscard: () => void
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

/** Builds a `HotspotConfirmCountdown`. `update` mutates the same notice in place. */
export function hotspotConfirmCountdown(
  props: HotspotConfirmCountdownProps,
): Component<HotspotConfirmCountdownProps> {
  let currentProps = props
  let currentDeadlineMs = props.deadlineMs
  let secondsRemaining = remainingSeconds(props.deadlineMs)
  const announcedThresholds = new Set<number>()

  const remainingSpan = el('span', { class: 'font-tabular' }, [])

  const messageParagraph = el('p', { class: 'm-0' }, [
    el('strong', { class: 'font-semibold' }, ['Confirm this hotspot to keep it.']),
    ' It is running now, but Sentry will undo the change and restore the previous connection in ',
    remainingSpan,
    ' unless you confirm — that is what stops a hotspot nobody can reach from surviving a reboot.',
  ])
  const safetyParagraph = el('p', { class: 'm-0 text-[11px]' }, [
    'If you have just joined the new network and can still see this page, confirming is safe.',
  ])

  const confirmButton = baseButton({
    variant: 'on-bright',
    disabled: props.busy ?? false,
    onClick: () => currentProps.onConfirm(),
    children: ['Keep this hotspot'],
  })
  const discardButton = baseButton({
    variant: 'on-bright',
    disabled: props.busy ?? false,
    onClick: () => currentProps.onDiscard(),
    children: ['Stop it now'],
  })
  const buttonRow = el('div', { class: 'flex flex-wrap gap-2' }, [
    confirmButton.element,
    discardButton.element,
  ])

  const bodyWrapper = el('div', { class: 'flex flex-col gap-3' }, [
    messageParagraph,
    safetyParagraph,
    buttonRow,
  ])
  const notice = noticeBox({ tone: 'warn', role: 'status', children: [bodyWrapper] })

  function renderRemaining(): void {
    setText(remainingSpan, formatRemaining(secondsRemaining))
  }

  function tick(): void {
    secondsRemaining = remainingSeconds(currentDeadlineMs)
    renderRemaining()
    for (const threshold of ANNOUNCE_AT_SECONDS) {
      if (secondsRemaining <= threshold && !announcedThresholds.has(threshold)) {
        announcedThresholds.add(threshold)
        liveAnnouncer().announcePolite(
          `${threshold} seconds left to confirm the hotspot, or it will be rolled back.`,
        )
      }
    }
  }

  const intervalId = setInterval(tick, 1000)

  renderRemaining()

  return {
    element: notice.element,

    update(nextProps): void {
      currentProps = nextProps
      // A new confirmation window is a new set of checkpoints.
      if (nextProps.deadlineMs !== currentDeadlineMs) {
        currentDeadlineMs = nextProps.deadlineMs
        announcedThresholds.clear()
        secondsRemaining = remainingSeconds(currentDeadlineMs)
        renderRemaining()
      }
      confirmButton.update({
        variant: 'on-bright',
        disabled: nextProps.busy ?? false,
        onClick: () => currentProps.onConfirm(),
        children: ['Keep this hotspot'],
      })
      discardButton.update({
        variant: 'on-bright',
        disabled: nextProps.busy ?? false,
        onClick: () => currentProps.onDiscard(),
        children: ['Stop it now'],
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
