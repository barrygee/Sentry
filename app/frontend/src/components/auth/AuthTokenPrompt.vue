<script setup lang="ts">
import { ref, useId } from 'vue'

import BaseButton from '@/components/base/BaseButton.vue'
import BaseDialog from '@/components/base/BaseDialog.vue'
import BaseField from '@/components/base/BaseField.vue'
import SectionHeading from '@/components/base/SectionHeading.vue'
import { useAuthToken } from '@/composables/useAuthToken'

/**
 * Operator-facing prompt for `SENTRY_AUTH_TOKEN` (architecture §7.9) —
 * rendered once near the app root and driven entirely by
 * `useAuthToken().promptRequired`, which `api/client.ts` sets the moment any
 * request comes back `401`. Without this the console has no in-app way to
 * supply a token: every fetch and the SSE stream would 401 forever.
 */
const { promptRequired, setToken, dismissPrompt } = useAuthToken()

const headingId = useId()
const draft = ref('')

function submit(): void {
  if (draft.value.trim().length === 0) {
    return
  }
  setToken(draft.value)
  draft.value = ''
}
</script>

<template>
  <BaseDialog :open="promptRequired" :labelled-by="headingId" @close="dismissPrompt">
    <!-- A `<div>`, not `<header>`: teleported to `<body>`, outside any
         sectioning root, so `<header>` would double up as a second
         page-level "banner" landmark alongside `SdrsHeader`'s. -->
    <div class="flex flex-col gap-2">
      <SectionHeading :id="headingId">Authentication required</SectionHeading>
      <p class="m-0 text-[12.5px] leading-[1.55] text-signal-muted">
        This Sentry instance requires an operator token. Enter the value configured as
        <code class="font-mono">SENTRY_AUTH_TOKEN</code> to continue — it is kept only for this
        browser tab.
      </p>
    </div>
    <form class="flex flex-col gap-3" @submit.prevent="submit">
      <BaseField v-model="draft" label="Access token" />
      <div class="flex justify-end gap-2">
        <BaseButton type="submit" variant="primary">Connect</BaseButton>
      </div>
    </form>
  </BaseDialog>
</template>
