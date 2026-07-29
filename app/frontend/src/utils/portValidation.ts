import type { PortConstraints } from '@/api/client'

/**
 * Mirrors the port-allocator rule table (architecture §8) for instant
 * inline feedback. Advisory only — the server always re-validates on
 * `PATCH`, and rule 6 (live bind probe) can't be checked client-side at
 * all, so a server `409` must still be rendered in the same message slot.
 */
export function validatePortClientSide(
  port: number,
  constraints: PortConstraints,
  ownReservedPorts: readonly number[] = [],
): string | null {
  if (!Number.isInteger(port)) {
    return 'Port must be a whole number.'
  }
  const controlPort = port + 2
  if (port < constraints.port_min || controlPort > constraints.port_max) {
    return `Port must leave room for ${port}-${controlPort} within ${constraints.port_min}-${constraints.port_max}.`
  }
  const [internalRangeStart, internalRangeEnd] = constraints.internal_range
  if (
    isWithinRange(port, internalRangeStart, internalRangeEnd) ||
    isWithinRange(controlPort, internalRangeStart, internalRangeEnd)
  ) {
    return `Ports ${internalRangeStart}-${internalRangeEnd - 1} are reserved for internal use.`
  }
  if (constraints.reserved.includes(port) || constraints.reserved.includes(controlPort)) {
    return 'That port is reserved by the operator.'
  }
  const conflicting = constraints.in_use.filter((usedPort) => !ownReservedPorts.includes(usedPort))
  if (conflicting.includes(port) || conflicting.includes(controlPort)) {
    return `Port ${port} (or its control port ${controlPort}) is already assigned to another device.`
  }
  return null
}

function isWithinRange(value: number, start: number, end: number): boolean {
  return value >= start && value < end
}
