import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import { dismissNotice, sdrsStore } from '../../state/sdrsStore.js'
import type { NoticeItem, NoticeLevel } from '../../types/sdrs.js'
import { confirmIconAction } from '../base/confirmIconAction.js'
import type { NoticeTone } from '../base/noticeBox.js'
import { noticeBox } from '../base/noticeBox.js'

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

/** One notice row: a dismissible `NoticeBox` keyed by the notice's own id. */
function noticeListItem(notice: NoticeItem): Component<NoticeItem> {
  let currentNotice = notice

  const messageParagraph = el('p', { class: 'm-0' }, [notice.message])

  const dismissAction = confirmIconAction({
    accessibleName: `Dismiss notice: ${notice.message}`,
    confirmAccessibleName: 'Confirm dismiss notice',
    cancelAccessibleName: 'Cancel dismissing notice',
    armedAnnouncement: 'Confirm dismissing this notice, or cancel.',
    cancelledAnnouncement: 'Dismissing notice cancelled.',
    onConfirm: () => dismissNotice(currentNotice.id),
  })
  dismissAction.element.classList.add('self-start')

  const row = el(
    'div',
    { class: 'flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4' },
    [messageParagraph, dismissAction.element],
  )

  const box = noticeBox({
    tone: toneFor(notice.level),
    role: roleFor(notice.level),
    children: [row],
  })

  const listItem = el('li', {}, [box.element])

  return {
    element: listItem,

    update(nextNotice): void {
      currentNotice = nextNotice
      setText(messageParagraph, nextNotice.message)
      box.update({
        tone: toneFor(nextNotice.level),
        role: roleFor(nextNotice.level),
        children: [row],
      })
      dismissAction.update({
        accessibleName: `Dismiss notice: ${nextNotice.message}`,
        confirmAccessibleName: 'Confirm dismiss notice',
        cancelAccessibleName: 'Cancel dismissing notice',
        armedAnnouncement: 'Confirm dismissing this notice, or cancel.',
        cancelledAnnouncement: 'Dismissing notice cancelled.',
        onConfirm: () => dismissNotice(currentNotice.id),
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
 */
export function noticeList(): Component<void> {
  const listElement = el('ul', {
    class: 'm-0 flex list-none flex-col gap-2 p-0',
    attrs: { 'aria-label': 'Notices' },
  })

  const list = keyedList<NoticeItem, string>(listElement, noticeListItem, (notice) => notice.id)

  const unsubscribe = watchStore(sdrsStore, (state) => {
    const visibleNotices = state.notices.filter((notice) => !notice.dismissed)
    setVisible(listElement, visibleNotices.length > 0)
    list.update(visibleNotices)
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
