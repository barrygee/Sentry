import { describe, expect, it } from 'vitest'

import {
  parseCoordinate,
  validateCoordinatePair,
  validateLatitude,
  validateLongitude,
} from '../../src/utils/locationValidation.js'

/**
 * Tests for the coordinate checks behind the Sentry Location fields.
 *
 * The distinction these exist to protect is "left blank" versus "typed
 * nonsense". Blank is a *valid* value here — clearing both fields is how an
 * operator removes the position — so a parser that collapsed the two would
 * silently erase a Sentry's location whenever someone fat-fingered a letter
 * into the box.
 */

describe('parseCoordinate', () => {
  it('reads a plain decimal', () => {
    expect(parseCoordinate('54.95149')).toBe(54.95149)
  })

  it('reads a negative decimal', () => {
    expect(parseCoordinate('-1.53586')).toBe(-1.53586)
  })

  it('ignores surrounding whitespace', () => {
    expect(parseCoordinate('  54.95149  ')).toBe(54.95149)
  })

  it('treats an empty field as no value rather than zero', () => {
    // The distinction the whole module rests on: `0` is a real coordinate, so
    // returning it for a blank field would place an un-positioned Sentry on the
    // equator instead of leaving it unplaced.
    expect(parseCoordinate('')).toBeNull()
  })

  it('treats a whitespace-only field as no value', () => {
    expect(parseCoordinate('   ')).toBeNull()
  })

  it('reads zero as zero, not as blank', () => {
    expect(parseCoordinate('0')).toBe(0)
  })

  it('returns NaN for text that is not a number', () => {
    expect(parseCoordinate('north')).toBeNaN()
  })

  it('rejects a number with a trailing word rather than salvaging the digits', () => {
    // `parseFloat('54.9 north')` would return 54.9 and silently accept half an
    // entry, which is precisely the failure this uses `Number()` to avoid.
    expect(parseCoordinate('54.9 north')).toBeNaN()
  })
})

describe('validateLatitude', () => {
  it('accepts a blank field', () => {
    expect(validateLatitude(null)).toBeNull()
  })

  it.each([-90, 0, 90, 54.95149])('accepts %s', (latitude) => {
    expect(validateLatitude(latitude)).toBeNull()
  })

  it.each([-90.1, 90.1, 900])('rejects %s as off the globe', (latitude) => {
    expect(validateLatitude(latitude)).toMatch(/between -90 and 90/)
  })

  it('rejects text that parsed to NaN', () => {
    expect(validateLatitude(Number.NaN)).toMatch(/must be a number/)
  })

  it('names the field it is complaining about', () => {
    expect(validateLatitude(91)).toMatch(/^Latitude/)
  })
})

describe('validateLongitude', () => {
  it('accepts a blank field', () => {
    expect(validateLongitude(null)).toBeNull()
  })

  it.each([-180, 0, 180, -1.53586])('accepts %s', (longitude) => {
    expect(validateLongitude(longitude)).toBeNull()
  })

  it.each([-180.1, 180.1, 900])('rejects %s as off the globe', (longitude) => {
    expect(validateLongitude(longitude)).toMatch(/between -180 and 180/)
  })

  it('rejects text that parsed to NaN', () => {
    expect(validateLongitude(Number.NaN)).toMatch(/must be a number/)
  })

  it('names the field it is complaining about', () => {
    expect(validateLongitude(181)).toMatch(/^Longitude/)
  })

  it('accepts a longitude a latitude check would have rejected', () => {
    // Guards against the two validators being wired to the same bounds — the
    // mistake that would let 150°W through as a latitude.
    expect(validateLongitude(-150)).toBeNull()
    expect(validateLatitude(-150)).not.toBeNull()
  })
})

describe('validateCoordinatePair', () => {
  it('accepts a complete pair', () => {
    expect(validateCoordinatePair(54.95149, -1.53586)).toBeNull()
  })

  it('accepts two blanks as a deliberate erasure', () => {
    expect(validateCoordinatePair(null, null)).toBeNull()
  })

  it('accepts a pair at zero', () => {
    expect(validateCoordinatePair(0, 0)).toBeNull()
  })

  it('rejects a longitude with no latitude, naming the missing one', () => {
    expect(validateCoordinatePair(null, -1.53586)).toMatch(/latitude/)
  })

  it('rejects a latitude with no longitude, naming the missing one', () => {
    expect(validateCoordinatePair(54.95149, null)).toMatch(/longitude/)
  })
})
