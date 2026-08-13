/**
 * Client-side checks for the Sentry Location fields, mirroring
 * `schemas/location.py`. Advisory only — the server re-validates every `PUT`,
 * and its rejection is rendered in the same message slot these produce.
 *
 * The point of validating here at all is that a mistyped coordinate is silent
 * otherwise: a longitude entered where a latitude belongs is a perfectly valid
 * number that puts this Sentry somewhere it is not, on every Sentinel watching.
 */

export const MINIMUM_LATITUDE = -90
export const MAXIMUM_LATITUDE = 90
export const MINIMUM_LONGITUDE = -180
export const MAXIMUM_LONGITUDE = 180

/**
 * Parse an operator-typed coordinate.
 *
 * Returns `null` for an empty field — which is a *valid* value here, meaning
 * "no position" — and `NaN` for text that is not a number at all, so a caller
 * can tell "left blank" from "typed nonsense". `Number()` rather than
 * `parseFloat`: `parseFloat('54.9 north')` happily returns `54.9`, and silently
 * accepting half an entry is the failure mode this whole module exists to stop.
 */
export function parseCoordinate(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') {
    return null
  }
  return Number(trimmed)
}

/** Validate a latitude, or `null` for an empty field. Returns an error message or `null`. */
export function validateLatitude(value: number | null): string | null {
  return validateCoordinate(value, MINIMUM_LATITUDE, MAXIMUM_LATITUDE, 'Latitude')
}

/** Validate a longitude, or `null` for an empty field. Returns an error message or `null`. */
export function validateLongitude(value: number | null): string | null {
  return validateCoordinate(value, MINIMUM_LONGITUDE, MAXIMUM_LONGITUDE, 'Longitude')
}

/**
 * Enforce the server's both-or-neither rule before a round trip.
 *
 * Half a position cannot be plotted, so it is never a state worth storing —
 * and catching it here names the empty field instead of returning a 422 that
 * talks about the pair.
 */
export function validateCoordinatePair(
  latitude: number | null,
  longitude: number | null,
): string | null {
  if (latitude === null && longitude !== null) {
    return 'Enter a latitude too, or clear both to remove this Sentry’s position.'
  }
  if (longitude === null && latitude !== null) {
    return 'Enter a longitude too, or clear both to remove this Sentry’s position.'
  }
  return null
}

function validateCoordinate(
  value: number | null,
  minimum: number,
  maximum: number,
  fieldName: string,
): string | null {
  if (value === null) {
    return null
  }
  if (!Number.isFinite(value)) {
    return `${fieldName} must be a number in decimal degrees, e.g. 54.95149.`
  }
  if (value < minimum || value > maximum) {
    return `${fieldName} must be between ${minimum} and ${maximum}.`
  }
  return null
}
