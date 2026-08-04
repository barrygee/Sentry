<script setup lang="ts">
import { computed, ref, useId } from 'vue'

import BaseButton from '@/components/base/BaseButton.vue'
import BaseField from '@/components/base/BaseField.vue'
import { validatePassphraseClientSide } from '@/utils/hotspotValidation'

/**
 * The hotspot password field, and the "leave it unchanged" affordance that
 * makes the write-only passphrase workable.
 *
 * The server never returns a stored password, so there is nothing to prefill.
 * Rather than presenting an empty box that would silently clear the key (or
 * demand it be retyped on every unrelated edit), a configured hotspot shows
 * *"A password is set"* plus an explicit **Change password** control. Not
 * re-asking for something unchanged is WCAG 3.3.7 Redundant Entry, not merely a
 * convenience — and it is what keeps `passphrase` absent from the request body,
 * which is the signal the API uses.
 *
 * The reveal toggle shows what the operator has just typed, never what the
 * server holds. That is the accessible form of "show password" (WCAG 3.3.8):
 * it helps someone check a long key they entered without ever turning a stored
 * secret into a readable one.
 */
const modelValue = defineModel<string>({ required: true })

const props = withDefaults(
  defineProps<{
    /** Whether the server reports a stored password for this hotspot. */
    passphraseSet: boolean
    /** A server-side error for this field, rendered in the same slot as the local one. */
    serverError?: string | null
    disabled?: boolean
  }>(),
  { serverError: null, disabled: false },
)

const emit = defineEmits<{ 'update:changing': [boolean] }>()

const revealed = ref(false)
const touched = ref(false)
// A configured hotspot starts in "keep the existing password" mode; a brand-new
// one has nothing to keep, so the field is open from the outset.
const changing = ref(!props.passphraseSet)
const descriptionId = useId()

const localError = computed(() => {
  if (!changing.value || !touched.value || modelValue.value === '') {
    return null
  }
  return validatePassphraseClientSide(modelValue.value)
})

const error = computed(() => props.serverError ?? localError.value)

function beginChanging(): void {
  changing.value = true
  modelValue.value = ''
  touched.value = false
  emit('update:changing', true)
}

function keepExisting(): void {
  changing.value = false
  revealed.value = false
  modelValue.value = ''
  touched.value = false
  emit('update:changing', false)
}

defineExpose({ isChanging: () => changing.value })
</script>

<template>
  <div class="flex flex-col gap-2">
    <template v-if="changing">
      <BaseField
        v-model="modelValue"
        label="Password"
        :type="revealed ? 'text' : 'password'"
        :error="error"
        :hint="
          error ? null : 'Clients need this to join. 8 to 63 characters — choose something long.'
        "
        :disabled="props.disabled"
        autocomplete="new-password"
        :described-by="passphraseSet ? descriptionId : null"
        @blur="touched = true"
      >
        <template #trailingAction>
          <!-- `aria-pressed` rather than a changing label alone, so the control's
               state is conveyed to assistive tech and not only by its text. -->
          <BaseButton
            variant="quiet"
            :aria-pressed="revealed"
            :aria-label="revealed ? 'Hide password' : 'Show password'"
            :disabled="props.disabled"
            @click="revealed = !revealed"
          >
            {{ revealed ? 'Hide' : 'Show' }}
          </BaseButton>
        </template>
      </BaseField>
      <p v-if="passphraseSet" :id="descriptionId" class="text-[11px] text-signal-muted">
        Saving replaces the current password. Every joined client will have to reconnect.
        <BaseButton variant="quiet" :disabled="props.disabled" @click="keepExisting">
          Keep current password
        </BaseButton>
      </p>
    </template>

    <template v-else>
      <!-- Mirrors BaseField's label geometry so this block lines up with the
           real fields above and below it rather than looking like loose prose. -->
      <span
        class="mb-1.5 block select-none font-sans text-[11px] font-semibold uppercase tracking-label text-ink-primary"
      >
        Password
      </span>
      <div class="flex flex-wrap items-center gap-3">
        <span class="font-tabular text-[12.5px] tracking-readout text-ink-primary">
          A password is set
        </span>
        <BaseButton variant="ghost" :disabled="props.disabled" @click="beginChanging">
          Change password
        </BaseButton>
      </div>
      <p class="text-[11px] text-signal-muted">
        Sentry never shows a saved password back to you. If it has been forgotten, set a new one.
      </p>
    </template>
  </div>
</template>
