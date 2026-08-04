<script setup lang="ts">
import { computed } from 'vue'

import BaseCopyButton from '@/components/base/BaseCopyButton.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'

/**
 * The one-time `.env` step, shown in the UI instead of sending an operator to
 * the README to retype it.
 *
 * These two settings are shown rather than *edited* on purpose, and it is not a
 * shortcut not taken. `SENTRY_HOTSPOT_CONTROL_ENABLED` is what makes driving the
 * host's NetworkManager from this container defensible instead of a privileged
 * sidecar (ADR-0007) — its whole value is that turning it on requires shell
 * access to the Pi, so a form that flipped it would delete the control it
 * represents. `SENTRY_AUTH_TOKEN` is the API's own credential, and this API is
 * unauthenticated by default; an endpoint that could set it would let anyone on
 * the LAN lock the owner out.
 *
 * So the UI does the part it usefully can: says exactly which lines are needed,
 * and lets them be copied without transcription errors.
 */
const props = defineProps<{
  /** Whether host WiFi control is switched on for this deployment. */
  controlEnabled: boolean
  /** Whether an API access token is configured. */
  authTokenConfigured: boolean
}>()

/** Only the lines actually missing — a satisfied prerequisite is not shown. */
const requiredLines = computed(() => {
  const lines: string[] = []
  if (!props.controlEnabled) {
    lines.push('SENTRY_HOTSPOT_CONTROL_ENABLED=true')
  }
  if (!props.authTokenConfigured) {
    lines.push('SENTRY_AUTH_TOKEN=<a long random value>')
  }
  return lines
})

const envBlock = computed(() => requiredLines.value.join('\n'))
</script>

<template>
  <NoticeBox tone="warn" role="alert">
    <div class="flex flex-col gap-3">
      <p class="m-0">
        <strong class="font-semibold">One-time setup on the Pi.</strong>
        Add
        {{ requiredLines.length === 1 ? 'this line' : 'these lines' }} to Sentry’s
        <code class="font-tabular">.env</code> file and restart it (<code class="font-tabular"
          >docker compose restart</code
        >).
      </p>

      <pre
        class="m-0 overflow-x-auto rounded-rack bg-ground-raised px-3 py-2 font-tabular text-[12px] leading-[1.7] text-ink-primary"
      ><code>{{ envBlock }}</code></pre>

      <BaseCopyButton
        :value="envBlock"
        accessible-name="Copy the required .env settings"
        label="Copy these settings"
      />

      <p v-if="!controlEnabled" class="m-0 text-[11px] leading-[1.6]">
        Hotspot control is off by default because it is the one setting that lets this web API
        reconfigure the Pi’s own networking. Turning it on is deliberately something only someone
        with access to the Pi can do.
      </p>
      <p v-if="!authTokenConfigured" class="m-0 text-[11px] leading-[1.6]">
        The access token is required before a hotspot can start: once the network is up, anyone in
        range who has its password is on the same network as this API.
      </p>
    </div>
  </NoticeBox>
</template>
