/**
 * Client-side mirror of the server's EEPROM serial allow-list (architecture
 * §7.6 guard 2, `SERIAL_PATTERN` in `app/backend/schemas/serial.py`). Advisory
 * only — the server always re-validates, and a `422` still renders in the
 * same message slot as this check (architecture §9.4 forms rule).
 */
export const SERIAL_PATTERN = /^[A-Za-z0-9_-]{1,32}$/

/** Returns a human-readable error, or `null` when `serial` would be accepted. */
export function validateSerialClientSide(serial: string): string | null {
  if (serial.length === 0) {
    return 'Serial is required.'
  }
  if (!SERIAL_PATTERN.test(serial)) {
    return 'Only letters, numbers, hyphens and underscores are allowed, 1-32 characters.'
  }
  return null
}
