import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import { deviceLabel, dismissNotice, sdrsStore } from '../../state/sdrsStore.js'
import type { NoticeItem, NoticeLevel } from '../../types/sdrs.js'
import type { ConfirmIconActionProps } from '../base/confirmIconAction.js'
import { confirmIconAction } from '../base/confirmIconAction.js'
import type { NoticeTone } from '../base/noticeBox.js'
import { noticeBox } from '../base/noticeBox.js'

/** One notice, paired with the name of the device it is about (`null` when SDR-wide). */
interface NoticeRow {
  notice: NoticeItem
  deviceName: string | null
}

function roleFor(level: NoticeLevel): 'status' | 'alert' {
  return level === 'info' ? 'status' : 'alert'
}

function toneFor(level: NoticeLevel): NoticeTone {
  switch (level) {
    case 'error':
      return 'danger'
    case 'warn':
      return 'warn'
    default:
      return 'info'
  }
}

/**
 * The dismiss control's accessible name.
 *
 * The device goes first, because the messages are written to describe a
 * condition rather than to identify a device — several of them are byte-
 * identical across devices — and a screen-reader user tabbing the list would
 * otherwise hear the same long sentence repeatedly before reaching the word
 * that distinguishes one row from the next.
 */
function dismissAccessibleName(row: NoticeRow): string {
  const subject =
    row.deviceName === null
      ? `Dismiss notice: ${row.notice.message}`
      : `Dismiss notice for ${row.deviceName}: ${row.notice.message}`
  // Spelled out rather than reusing the visible "×3": a screen reader renders
  // that glyph as "multiplication sign 3", or skips it entirely.
  return row.notice.repeatCount > 1
    ? `${subject} (repeated ${row.notice.repeatCount} times)`
    : subject
}

/** One notice row: a dismissible `NoticeBox` keyed by the notice's own id. */
function noticeListItem(row: NoticeRow): Component<NoticeRow> {
  let currentRow = row

  // Not a heading: it names the subject of this one message rather than
  // introducing a section, and a run of same-level headings through the log
  // would clutter a screen reader's heading list without structuring anything.
  const deviceNameElement = el('span', { class: 'font-semibold' })
  const messageElement = el('span')
  // `aria-hidden` because the count is already spelled out in the dismiss
  // control's accessible name — announcing the glyph too would say it twice,
  // once unintelligibly.
  const repeatCountElement = el('span', {
    class: 'ml-2 whitespace-nowrap font-semibold tabular-nums opacity-80',
    attrs: { 'aria-hidden': 'true' },
  })
  const messageParagraph = el('p', { class: 'm-0' }, [
    deviceNameElement,
    messageElement,
    repeatCountElement,
  ])

  // One definition, used to build the control and to refresh it — the two were
  // identical six-property literals, and the constructor's copy was overwritten
  // by the first `render` before anything could reach it.
  function dismissProps(forRow: NoticeRow): ConfirmIconActionProps {
    return {
      accessibleName: dismissAccessibleName(forRow),
      confirmAccessibleName: 'Confirm dismiss notice',
      cancelAccessibleName: 'Cancel dismissing notice',
      armedAnnouncement: 'Confirm dismissing this notice, or cancel.',
      cancelledAnnouncement: 'Dismissing notice cancelled.',
      // Reads `currentRow`, not `forRow`: the click happens long after this is
      // built, and must dismiss whatever the row holds by then.
      onConfirm: () => dismissNotice(currentRow.notice.id),
    }
  }

  const dismissAction = confirmIconAction(dismissProps(row))
  dismissAction.element.classList.add('self-start')

  const rowElement = el(
    'div',
    { class: 'flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4' },
    [messageParagraph, dismissAction.element],
  )

  const box = noticeBox({
    tone: toneFor(row.notice.level),
    role: roleFor(row.notice.level),
    children: [rowElement],
  })

  const listItem = el('li', {}, [box.element])

  function render(nextRow: NoticeRow): void {
    // The separator travels with the name so it disappears with it, rather than
    // leaving a stray "— " in front of an SDR-wide notice.
    setText(deviceNameElement, nextRow.deviceName === null ? '' : `${nextRow.deviceName} — `)
    setText(messageElement, nextRow.notice.message)
    setText(
      repeatCountElement,
      nextRow.notice.repeatCount > 1 ? `×${nextRow.notice.repeatCount}` : '',
    )
    dismissAction.update(dismissProps(nextRow))
  }

  render(row)

  return {
    element: listItem,

    update(nextRow): void {
      currentRow = nextRow
      render(nextRow)
      box.update({
        tone: toneFor(nextRow.notice.level),
        role: roleFor(nextRow.notice.level),
        children: [rowElement],
      })
    },

    destroy(): void {
      dismissAction.destroy()
      box.destroy()
    },
  }
}

/**
 * The SDR-wide operational notice log (architecture §7.3 SSE `notice`
 * events, plus every failed PATCH/serial-flash attempt) — `sdrsStore` has
 * always collected these, but until this component nothing rendered them:
 * `crash_loop`, `spawn_failed`, `index_unresolved`, `relay_wedge_exit` and
 * `port_conflict` were silently swallowed, and `dismissNotice` was
 * unreachable. Each notice is independently dismissible and keyboard
 * reachable; `info` notices use `role="status"`, `warn`/`error` use
 * `role="alert"` so they interrupt appropriately without duplicating the
 * app-root live announcer (this list is the persistent record, not the
 * announcement itself).
 *
 * A notice that names a device is prefixed with that device's name. The
 * server's messages describe the condition and nothing else — `crash_loop`
 * reads the same whichever dongle is looping — so two dongles crash-looping
 * produced two identical rows with no way to tell which was which, or that
 * they were about different devices at all. The name is resolved here against
 * live store state rather than captured when the notice arrived, so renaming a
 * device relabels its outstanding notices too.
 *
 * Repeats are coalesced into one row carrying a `×N` count (see the store's
 * `applyNotice`), so a dongle flapping every few seconds cannot bury the rest
 * of the log.
 */
export function noticeList(): Component<void> {
  const listElement = el('ul', {
    class: 'm-0 flex list-none flex-col gap-2 p-0',
    attrs: { 'aria-label': 'Notices' },
  })

  const list = keyedList<NoticeRow, string>(
    listElement,
    noticeListItem,
    (noticeRow) => noticeRow.notice.id,
  )

  const unsubscribe = watchStore(sdrsStore, (state) => {
    const visibleRows = state.notices
      .filter((notice) => !notice.dismissed)
      .map((notice) => ({
        notice,
        deviceName: notice.device_id === null ? null : deviceLabel(state, notice.device_id),
      }))
    setVisible(listElement, visibleRows.length > 0)
    list.update(visibleRows)
  })

  return {
    element: listElement,

    update(): void {
      // Store-driven — `watchStore` above keeps the list current on every
      // change, so there is nothing for an external caller to pass in.
    },

    destroy(): void {
      unsubscribe()
      list.destroy()
    },
  }
}
