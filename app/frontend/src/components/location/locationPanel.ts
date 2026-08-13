import { el, setText, setVisible } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { watchStore } from '../../core/observable.js'
import {
  hasLocation,
  locationStore,
  saveLocation,
  type LocationState,
} from '../../state/locationStore.js'
import { baseButton } from '../base/baseButton.js'
import { baseField } from '../base/baseField.js'
import { nextElementId } from '../base/idGenerator.js'
import { noticeBox } from '../base/noticeBox.js'
import { disclosureSection } from '../base/disclosureSection.js'
import {
  parseCoordinate,
  validateCoordinatePair,
  validateLatitude,
  validateLongitude,
} from '../../utils/locationValidation.js'

/**
 * The Settings section for this Sentry's fixed position.
 *
 * The coordinates exist for Sentinel's benefit, not this console's: they travel
 * with the device list Sentinel already fetches (`GET /api/status`,
 * `GET /api/v1/sdrs`) so it can plot this Pi on its map. Nothing in this UI
 * draws a map itself, which is why the panel is two fields and a save button
 * rather than a picker.
 *
 * A Sentry does not know where it is — no GPS, and geolocating a Pi by IP
 * places it at its ISP's exchange. The operator types it once, because they are
 * the only party that actually knows.
 *
 * Drafts live here rather than in the store, matching the password and hotspot
 * panels: a refresh that landed mid-edit would otherwise overwrite half-typed
 * coordinates with the saved ones.
 */
// Held once rather than repeated at construction and in `render`: the two must
// stay identical, and two copies of a hint string is exactly how they stop being.
const LATITUDE_HINT = 'Decimal degrees, -90 to 90.'
const LONGITUDE_HINT = 'Decimal degrees, -180 to 180.'

export function locationPanel(): Component<void> {
  const headingId = nextElementId('sentry-location-heading')

  // Empty string means "field cleared", which is a meaningful value here —
  // clearing both is how an operator removes the position — so drafts are held
  // as the raw text and only parsed at the point of saving.
  let draftLatitude = ''
  let draftLongitude = ''
  let draftInitialised = false
  let latitudeError: string | null = null
  let longitudeError: string | null = null
  let pairError: string | null = null

  const statusLine = el('p', { class: 'm-0 text-[12px] text-signal-muted' }, [])

  function onLatitudeChange(value: string): void {
    draftLatitude = value
    // Cleared as the operator types rather than re-validated: correcting a
    // rejected value should not keep shouting the old complaint at them while
    // they are halfway through typing the replacement.
    latitudeError = null
    pairError = null
    render(locationStore.state)
  }

  function onLongitudeChange(value: string): void {
    draftLongitude = value
    longitudeError = null
    pairError = null
    render(locationStore.state)
  }

  function onLatitudeBlur(): void {
    latitudeError = validateLatitude(parseCoordinate(draftLatitude))
    render(locationStore.state)
  }

  function onLongitudeBlur(): void {
    longitudeError = validateLongitude(parseCoordinate(draftLongitude))
    render(locationStore.state)
  }

  const latitudeField = baseField({
    label: 'Lat',
    value: '',
    inputMode: 'numeric',
    hint: LATITUDE_HINT,
    onChange: onLatitudeChange,
    onBlur: onLatitudeBlur,
  })

  const longitudeField = baseField({
    label: 'Lon',
    value: '',
    inputMode: 'numeric',
    hint: LONGITUDE_HINT,
    onChange: onLongitudeChange,
    onBlur: onLongitudeBlur,
  })

  const errorNotice = noticeBox({ tone: 'danger', role: 'alert', children: [] })

  const saveButton = baseButton({
    type: 'submit',
    variant: 'on-bright',
    children: ['Save location'],
  })

  const form = el(
    'form',
    {
      class: 'flex flex-col gap-4',
      on: {
        submit: (event) => {
          event.preventDefault()
          void submit()
        },
      },
    },
    [
      latitudeField.element,
      longitudeField.element,
      // Wrapped rather than bare: a direct child of a `flex-col` stretches to
      // the container's width, which is how the password and hotspot panels
      // keep their buttons button-sized too.
      el('div', { class: 'flex flex-wrap items-center justify-end gap-2' }, [saveButton.element]),
    ],
  )

  /** Validate both fields, then save. Nothing is sent while either is invalid. */
  async function submit(): Promise<void> {
    const latitude = parseCoordinate(draftLatitude)
    const longitude = parseCoordinate(draftLongitude)

    latitudeError = validateLatitude(latitude)
    longitudeError = validateLongitude(longitude)
    pairError =
      latitudeError === null && longitudeError === null
        ? validateCoordinatePair(latitude, longitude)
        : null

    if (latitudeError !== null || longitudeError !== null || pairError !== null) {
      render(locationStore.state)
      // Return focus to the field that was rejected — otherwise a screen-reader
      // user is told something is wrong without being taken to it.
      if (latitudeError !== null || (pairError !== null && latitude === null)) {
        latitudeField.focus()
      } else {
        longitudeField.focus()
      }
      return
    }

    const saved = await saveLocation(latitude, longitude)
    if (saved) {
      // Re-sync the drafts from what the server actually stored, so a value it
      // normalised is what the operator is left looking at.
      draftInitialised = false
      render(locationStore.state)
    }
    // No confirmation is rendered here. The server publishes a `notice` when a
    // position is stored, which the app-wide notice log shows and dismisses the
    // same way it does every other "something happened" message — including one
    // caused by another browser, which a banner local to this panel could never
    // report.
  }

  /** Format a stored coordinate for a text field. Empty string when unset. */
  function formatCoordinate(value: number | null): string {
    return value === null ? '' : String(value)
  }

  function render(state: Readonly<LocationState>): void {
    const busy = state.phase === 'saving' || state.phase === 'loading'

    // Adopt the server's values only when there is no edit in progress. Once
    // the operator has touched a field, the draft is the truth until it saves.
    if (!draftInitialised && state.phase !== 'loading' && state.phase !== 'saving') {
      draftLatitude = formatCoordinate(state.latitude)
      draftLongitude = formatCoordinate(state.longitude)
      draftInitialised = true
    }

    setText(
      statusLine,
      hasLocation(state) && state.updatedAt > 0
        ? `Last set ${new Date(state.updatedAt).toLocaleString()}.`
        : 'No position set — Sentinel cannot place this Sentry on its map yet.',
    )

    latitudeField.update({
      label: 'Lat',
      value: draftLatitude,
      inputMode: 'numeric',
      hint: LATITUDE_HINT,
      error: latitudeError,
      disabled: busy,
      onChange: onLatitudeChange,
      onBlur: onLatitudeBlur,
    })
    longitudeField.update({
      label: 'Lon',
      value: draftLongitude,
      inputMode: 'numeric',
      hint: LONGITUDE_HINT,
      error: longitudeError,
      disabled: busy,
      onChange: onLongitudeChange,
      onBlur: onLongitudeBlur,
    })
    saveButton.update({
      type: 'submit',
      variant: 'on-bright',
      disabled: busy,
      children: [state.phase === 'saving' ? 'Saving…' : 'Save location'],
    })

    // The pair rule is about both fields at once, so it is reported above them
    // rather than attached to either — hanging it off one would name the wrong
    // field as the problem half the time.
    const message = pairError ?? state.errorMessage
    setVisible(errorNotice.element, message !== null)
    if (message !== null) {
      errorNotice.update({ tone: 'danger', role: 'alert', children: [message] })
    }
  }

  const disclosure = disclosureSection({
    label: ['Sentry Location'],
    headingLevel: 2,
    headingId,
    tone: 'panel',
    defaultOpen: false,
    persistKey: 'sentry-location-panel',
    isBoxTitle: true,
    bodyClass: 'flex flex-col gap-6 pt-2',
    children: [
      el('div', { class: 'flex flex-col gap-2' }, [statusLine]),
      errorNotice.element,
      form,
    ],
  })

  const root = el(
    'section',
    {
      class: 'flex flex-col bg-ground-panel p-card',
      attrs: { 'aria-labelledby': headingId },
    },
    [disclosure.element],
  )

  const unsubscribe = watchStore(locationStore, render)

  return {
    element: root,

    update(): void {
      // Store-driven.
    },

    destroy(): void {
      unsubscribe()
      latitudeField.destroy()
      longitudeField.destroy()
      saveButton.destroy()
      errorNotice.destroy()
      disclosure.destroy()
    },
  }
}
