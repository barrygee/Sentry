import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'

/**
 * Tabular-figure numeric/mono display — the shared atom for every port,
 * frequency, PID, USB path and byte count so digits never shift width as
 * they tick (architecture §9.5 typography).
 */
export interface MonoValueProps {
  value: string | number
  unit?: string | null
}

/** Builds a `MonoValue`. `update` mutates the same text nodes in place. */
export function monoValue(props: MonoValueProps): Component<MonoValueProps> {
  const valueText = document.createTextNode(String(props.value))
  const unitSpan = el('span', { class: 'ml-0.5 text-signal-muted' }, [])

  const root = el('span', { class: 'font-tabular' }, [valueText, unitSpan])

  function applyUnit(unit: string | null | undefined): void {
    setVisible(unitSpan, Boolean(unit))
    setText(unitSpan, unit ?? '')
  }

  applyUnit(props.unit)

  return {
    element: root,

    update(nextProps): void {
      const nextText = String(nextProps.value)
      if (valueText.data !== nextText) {
        valueText.data = nextText
      }
      applyUnit(nextProps.unit)
    },

    destroy(): void {
      // No listeners, timers or subscriptions to release.
    },
  }
}
