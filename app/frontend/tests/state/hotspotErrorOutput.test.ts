import { beforeEach, describe, expect, it } from 'vitest'

import { ApiError } from '../../src/api/client.js'
import { hotspotStore, recordError, resetTransientState } from '../../src/state/hotspotStore.js'

/**
 * Tests for the failing command's output reaching the operator.
 *
 * A failed hotspot change carries `stderr_tail` — nmcli's own words, and the
 * only thing that says *why* it refused. The panel used to read it from
 * `state.last_error`, but on a failure the store keeps the *pre-request* state,
 * whose `last_error` is whatever it was before: almost always `null`. So the
 * one moment the detail mattered was the one moment nothing rendered, and the
 * message told the operator to go and read the Pi's logs for something the
 * response had already handed them.
 *
 * It is now taken off the error response itself, which is what these pin. The
 * server spreads the service error's context into the detail envelope, so
 * `stderr_tail` arrives as a sibling of `code` and `message`.
 */

function apiError(detail: Record<string, unknown> | null, status = 500): ApiError {
  return new ApiError(status, detail as never, 'fallback message')
}

// Verbatim from the Pi — the failure that made this visible.
const NMCLI_OUTPUT = "Error: 'sentry-hotspot' is not an active connection.\n"

describe('the failing command output on the hotspot store', () => {
  beforeEach(() => {
    hotspotStore.setState({
      phase: 'form',
      errorMessage: null,
      errorCode: null,
      errorCommandOutput: null,
    })
  })

  it('takes stderr_tail from the error response, not from the stale state', () => {
    recordError(
      apiError({
        code: 'hotspot_command_failed',
        message: 'The network command failed.',
        stderr_tail: NMCLI_OUTPUT,
      }),
      'Could not save the hotspot settings.',
    )

    expect(hotspotStore.state.errorCommandOutput).toBe(NMCLI_OUTPUT)
    expect(hotspotStore.state.errorCode).toBe('hotspot_command_failed')
  })

  it('records no output when the response carries none', () => {
    recordError(
      apiError({ code: 'passphrase_required', message: 'Set a password first.' }),
      'Could not save the hotspot settings.',
    )

    expect(hotspotStore.state.errorCommandOutput).toBeNull()
  })

  it('treats an empty stderr_tail as no output rather than an empty code block', () => {
    // The server sends `null` for this, but an empty string would render as a
    // bare `<pre>` with nothing in it — worse than omitting the block.
    recordError(
      apiError({ code: 'hotspot_command_failed', message: 'Failed.', stderr_tail: '' }),
      'Could not save the hotspot settings.',
    )

    expect(hotspotStore.state.errorCommandOutput).toBeNull()
  })

  it('ignores a non-string stderr_tail rather than rendering it', () => {
    recordError(
      apiError({ code: 'hotspot_command_failed', message: 'Failed.', stderr_tail: 42 }),
      'Could not save the hotspot settings.',
    )

    expect(hotspotStore.state.errorCommandOutput).toBeNull()
  })

  it('records nothing for a non-API failure, which has no response to read', () => {
    recordError(new TypeError('network down'), 'Could not save the hotspot settings.')

    expect(hotspotStore.state.errorCommandOutput).toBeNull()
    expect(hotspotStore.state.errorCode).toBe('hotspot_request_failed')
  })

  it('clears the output when transient state is reset', () => {
    // Leaving Settings must not park a command dump for the next visit — it
    // would describe an attempt made minutes ago, next to no message.
    recordError(
      apiError({ code: 'hotspot_command_failed', message: 'Failed.', stderr_tail: NMCLI_OUTPUT }),
      'Could not save the hotspot settings.',
    )

    resetTransientState()

    expect(hotspotStore.state.errorCommandOutput).toBeNull()
    expect(hotspotStore.state.errorMessage).toBeNull()
  })
})
