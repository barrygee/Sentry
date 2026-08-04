/**
 * Client-side mirrors of the hotspot's server rules
 * (`app/backend/schemas/hotspot.py`), for instant inline feedback.
 *
 * Advisory only, exactly like `portValidation`: the server re-validates every
 * request and its `422`/`409` message is rendered in the same slot. The rules
 * are duplicated here on purpose — the alternative is a round trip before an
 * operator learns their password is one character short — but they must not
 * drift, so each function names the server constant it mirrors.
 */

/** 802.11 caps the SSID element at 32 **octets**, mirroring `SSID_MAX_BYTES`. */
export const SSID_MAX_BYTES = 32

/** Mirrors `CHANNELS_2GHZ`. */
export const CHANNELS_2GHZ: readonly number[] = Array.from(
  { length: 14 },
  (_unused, index) => index + 1,
)

/** Mirrors `CHANNELS_5GHZ`. */
export const CHANNELS_5GHZ: readonly number[] = [
  36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149,
  153, 157, 161, 165,
]

// Matching control characters is the entire purpose of this pattern: an SSID
// containing one is rejected rather than being quietly passed to the radio.
const CONTROL_CHARACTERS = /[\x00-\x1f\x7f-\x9f]/
const PASSPHRASE_PATTERN = /^[\x20-\x7e]{8,63}$/
const RAW_PSK_PATTERN = /^[0-9a-fA-F]{64}$/

/**
 * Return the SSID's length in UTF-8 bytes.
 *
 * Not `ssid.length`: JavaScript counts UTF-16 code units, so an emoji reads as
 * 2 there and costs 4 on the wire. Eleven emoji is 44 bytes — over the limit
 * while `length` still says 22 — and a field that let it through would fail
 * server-side with no explanation the operator could act on.
 */
export function ssidByteLength(ssid: string): number {
  return new TextEncoder().encode(ssid).length
}

/** Validate a network name, returning an operator-facing message or `null`. */
export function validateSsidClientSide(ssid: string): string | null {
  if (CONTROL_CHARACTERS.test(ssid)) {
    return 'Network name must not contain control characters.'
  }
  if (ssid !== ssid.trim()) {
    return 'Network name must not start or end with a space.'
  }
  const byteLength = ssidByteLength(ssid)
  if (byteLength < 1) {
    return 'Network name is required.'
  }
  if (byteLength > SSID_MAX_BYTES) {
    return `Network name must be ${SSID_MAX_BYTES} bytes or fewer (this one is ${byteLength}). Accented and emoji characters cost more than one byte each.`
  }
  return null
}

/**
 * Validate a passphrase, returning an operator-facing message or `null`.
 *
 * Never trims. A leading or trailing space is a legal part of a WPA passphrase,
 * and quietly removing one would hand out credentials that do not work.
 */
export function validatePassphraseClientSide(passphrase: string): string | null {
  if (PASSPHRASE_PATTERN.test(passphrase) || RAW_PSK_PATTERN.test(passphrase)) {
    return null
  }
  return 'Password must be 8 to 63 characters using ordinary keyboard symbols, or a 64-character hexadecimal key.'
}

/** Validate a channel against its band, returning a message or `null`. `0` means automatic. */
export function validateChannelClientSide(channel: number, band: 'bg' | 'a'): string | null {
  if (channel === 0) {
    return null
  }
  const allowed = band === 'bg' ? CHANNELS_2GHZ : CHANNELS_5GHZ
  if (!allowed.includes(channel)) {
    const bandLabel = band === 'bg' ? '2.4 GHz' : '5 GHz'
    return `Channel ${channel} is not a ${bandLabel} channel. Choose Automatic instead.`
  }
  return null
}

/** The channel options for a band, with Automatic first. */
export function channelOptionsForBand(band: 'bg' | 'a'): { value: string; label: string }[] {
  const channels = band === 'bg' ? CHANNELS_2GHZ : CHANNELS_5GHZ
  return [
    { value: '0', label: 'Automatic' },
    ...channels.map((channel) => ({ value: String(channel), label: `Channel ${channel}` })),
  ]
}

/** Mirrors `GATEWAY_MIN_PREFIX` / `GATEWAY_MAX_PREFIX`. */
export const GATEWAY_MIN_PREFIX = 16
export const GATEWAY_MAX_PREFIX = 30

const IPV4_CIDR_PATTERN = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/

/**
 * Validate the hotspot's own address, returning a message or `null`.
 *
 * Mirrors `validate_gateway_cidr` on the server. Private ranges only: this
 * address is handed out by a DHCP server Sentry raises, and a public range
 * there would blackhole real internet destinations for every joined client.
 */
export function validateGatewayCidrClientSide(gatewayCidr: string): string | null {
  const match = IPV4_CIDR_PATTERN.exec(gatewayCidr.trim())
  if (!match) {
    return 'Address must look like 10.42.0.1/24.'
  }
  const octets = [match[1], match[2], match[3], match[4]].map((part) => Number(part))
  const prefixLength = Number(match[5])
  if (octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) {
    return 'Each part of the address must be between 0 and 255.'
  }
  if (prefixLength < GATEWAY_MIN_PREFIX || prefixLength > GATEWAY_MAX_PREFIX) {
    return `Network size must be between /${GATEWAY_MIN_PREFIX} and /${GATEWAY_MAX_PREFIX}.`
  }
  if (!isPrivateIpv4(octets)) {
    return 'Address must be in a private range (10.x, 172.16-31.x or 192.168.x).'
  }
  // The host bits must not be all-zero (the network address) or all-one (the
  // broadcast address) — neither is usable as this Sentry's own address.
  const addressAsInteger =
    ((octets[0] ?? 0) << 24) | ((octets[1] ?? 0) << 16) | ((octets[2] ?? 0) << 8) | (octets[3] ?? 0)
  const hostBitCount = 32 - prefixLength
  const hostMask = hostBitCount === 32 ? 0xffffffff : (1 << hostBitCount) - 1
  const hostBits = addressAsInteger & hostMask
  if (hostBits === 0) {
    return 'Address must not be the network address itself.'
  }
  if (hostBits === hostMask) {
    return 'Address must not be the broadcast address.'
  }
  return null
}

function isPrivateIpv4(octets: number[]): boolean {
  const [first = 0, second = 0] = octets
  if (first === 10) return true
  if (first === 172 && second >= 16 && second <= 31) return true
  if (first === 192 && second === 168) return true
  return false
}
