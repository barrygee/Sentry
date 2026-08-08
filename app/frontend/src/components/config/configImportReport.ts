import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { keyedList } from '../../core/component.js'
import type { ConfigImportResult, DeviceImportOutcome } from '../../api/client.js'
import { monoValue } from '../base/monoValue.js'
import { noticeBox } from '../base/noticeBox.js'
import { statusBadge } from '../base/statusBadge.js'
import type { StatusBadgeTone } from '../base/statusBadge.js'

/**
 * What an import actually did, entry by entry.
 *
 * A partial import is the *expected* outcome, not an error: the destination
 * Pi may not have every dongle plugged in yet, and one whose port is already
 * taken should not stop the rest from landing. A bare "imported" toast would
 * hide exactly the thing an operator needs to know — which of their devices
 * did not come across, and why.
 */
export interface ConfigImportReportProps {
  result: ConfigImportResult
}

const TONE_BY_OUTCOME: Record<DeviceImportOutcome['outcome'], StatusBadgeTone> = {
  applied: 'ok',
  skipped: 'neutral',
  failed: 'danger',
}

function summaryTone(result: ConfigImportResult): 'ok' | 'warn' | 'danger' {
  if (result.devices_failed > 0) return 'danger'
  if (result.devices_skipped > 0) return 'warn'
  return 'ok'
}

function summaryText(result: ConfigImportResult): string {
  const hotspotSuffix = result.hotspot_applied ? ' · hotspot settings written' : ''
  return `${result.devices_applied} applied · ${result.devices_skipped} skipped · ${result.devices_failed} failed${hotspotSuffix}.`
}

function entryKey(entry: DeviceImportOutcome): string {
  return `${entry.identity_kind}:${entry.identity_key}`
}

function importEntryRow(entry: DeviceImportOutcome): Component<DeviceImportOutcome> {
  const badge = statusBadge({ tone: TONE_BY_OUTCOME[entry.outcome], children: [entry.outcome] })
  const identityMono = monoValue({ value: entryKey(entry) })
  const identityWrapper = el('span', { class: 'text-[12px] text-ink-primary' }, [
    identityMono.element,
  ])
  const detailSpan = el('span', { class: 'w-full text-[11px] leading-[1.6] text-signal-muted' }, [])

  const root = el(
    'li',
    {
      class: 'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-rack bg-ground-raised px-3 py-2',
    },
    [badge.element, identityWrapper, detailSpan],
  )

  function render(current: DeviceImportOutcome): void {
    badge.update({ tone: TONE_BY_OUTCOME[current.outcome], children: [current.outcome] })
    identityMono.update({ value: entryKey(current) })
    setVisible(detailSpan, Boolean(current.detail))
    setText(detailSpan, current.detail)
  }

  render(entry)

  return {
    element: root,
    update: render,
    destroy(): void {
      badge.destroy()
      identityMono.destroy()
    },
  }
}

/** Builds a `ConfigImportReport`. `update` mutates the same summary/entry nodes in place. */
export function configImportReport(
  props: ConfigImportReportProps,
): Component<ConfigImportReportProps> {
  const summaryNotice = noticeBox({
    tone: summaryTone(props.result),
    role: 'status',
    children: [summaryText(props.result)],
  })
  const hotspotDetailParagraph = el(
    'p',
    { class: 'm-0 text-[11px] leading-[1.6] text-signal-muted' },
    [],
  )
  const list = el('ul', {
    class: 'm-0 flex list-none flex-col gap-2 p-0',
    attrs: { 'aria-label': 'Import results' },
  })
  const listController = keyedList<DeviceImportOutcome, string>(list, importEntryRow, entryKey)

  const root = el('div', { class: 'flex flex-col gap-3' }, [
    summaryNotice.element,
    hotspotDetailParagraph,
    list,
  ])

  function render(result: ConfigImportResult): void {
    summaryNotice.update({
      tone: summaryTone(result),
      role: 'status',
      children: [summaryText(result)],
    })
    setVisible(hotspotDetailParagraph, Boolean(result.hotspot_detail))
    setText(
      hotspotDetailParagraph,
      result.hotspot_detail ? `Hotspot: ${result.hotspot_detail}` : '',
    )
    const entries = result.devices ?? []
    setVisible(list, entries.length > 0)
    listController.update(entries)
  }

  render(props.result)

  return {
    element: root,

    update(nextProps): void {
      render(nextProps.result)
    },

    destroy(): void {
      summaryNotice.destroy()
      listController.destroy()
    },
  }
}
