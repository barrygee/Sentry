<script setup lang="ts">
import { computed, ref, useId } from 'vue'

import BaseButton from '@/components/base/BaseButton.vue'
import BaseDialog from '@/components/base/BaseDialog.vue'
import BaseToggle from '@/components/base/BaseToggle.vue'
import DataCell from '@/components/base/DataCell.vue'
import NoticeBox from '@/components/base/NoticeBox.vue'
import SectionHeading from '@/components/base/SectionHeading.vue'
import ConfigImportReport from '@/components/config/ConfigImportReport.vue'
import { useConfigStore } from '@/stores/config'

/**
 * Download this Sentry's configuration, or apply one exported from another.
 *
 * The reason this exists: standing up a second Pi otherwise means retyping
 * every device's name, port, antenna and visibility by hand and getting all of
 * them right.
 *
 * Importing is deliberately two steps — pick a file, see what it contains, then
 * confirm. An import rewrites every device's configuration, which is too much
 * to happen as a side effect of a file-picker closing.
 *
 */
const configStore = useConfigStore()

const headingId = useId()
const fileInput = ref<HTMLInputElement | null>(null)

const isBusy = computed(() => configStore.phase === 'importing')

/**
 * Save the configuration as a file.
 *
 * Fetches through the authenticated API client and builds the file locally,
 * rather than linking straight at `/api/config/download`. A plain navigation
 * cannot set an `Authorization` header, so a link would 401 the moment an
 * operator sets a token — and the alternative, putting the token in the URL as
 * `EventSource` has to, would write a credential into browser history and the
 * access log. `EventSource` has no choice; this does.
 */
async function downloadConfig(): Promise<void> {
  await configStore.loadPreview()
  if (configStore.preview === null) {
    return
  }
  const blob = new Blob([JSON.stringify(configStore.preview, null, 2) + '\n'], {
    type: 'application/json',
  })
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = 'sentry-config.json'
  link.click()
  URL.revokeObjectURL(objectUrl)
}

function pickFile(): void {
  fileInput.value?.click()
}

async function onFileChosen(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }
  configStore.stagePickedFile(file.name, await file.text())
  // Clear the input so picking the *same* file again still fires `change`.
  input.value = ''
}

async function applyImport(): Promise<void> {
  await configStore.applyPendingImport()
}

function close(): void {
  configStore.closeDialog()
}
</script>

<template>
  <BaseDialog
    :open="configStore.dialogOpen"
    :labelled-by="headingId"
    :disable-dismiss="isBusy"
    @close="close"
  >
    <div class="flex max-h-[80vh] flex-col gap-6 overflow-y-auto">
      <!-- A div rather than <header>: this is teleported to <body>, and a
           second banner landmark on the page would be wrong. -->
      <div class="flex flex-col gap-2">
        <SectionHeading :id="headingId" :level="2">Configuration</SectionHeading>
        <p class="m-0 text-[12px] leading-[1.6] text-signal-muted">
          Move a whole Sentry setup to another Pi. The file carries every configured device’s name,
          port, antenna, notes and visibility — never any password.
        </p>
      </div>

      <p role="status" class="sr-only">{{ isBusy ? 'Importing configuration.' : '' }}</p>
      <p role="alert" class="sr-only">{{ configStore.errorMessage ?? '' }}</p>

      <NoticeBox v-if="configStore.errorMessage" tone="danger" role="status">
        {{ configStore.errorMessage }}
      </NoticeBox>

      <section class="flex flex-col gap-3" aria-labelledby="config-export-heading">
        <SectionHeading id="config-export-heading" :level="3">Export</SectionHeading>
        <dl class="m-0 grid grid-cols-2 gap-x-6 gap-y-4">
          <DataCell
            label="Configured devices"
            label-tag="dt"
            value-tag="dd"
            :value="configStore.exportDeviceCount"
          />
          <DataCell
            label="Hotspot"
            label-tag="dt"
            value-tag="dd"
            :value="configStore.preview?.hotspot ? 'Included' : 'Not set up'"
          />
        </dl>
        <div>
          <BaseButton variant="ghost" :disabled="isBusy" @click="downloadConfig">
            Download configuration
          </BaseButton>
        </div>
      </section>

      <section class="flex flex-col gap-3" aria-labelledby="config-import-heading">
        <SectionHeading id="config-import-heading" :level="3">Import</SectionHeading>

        <input
          ref="fileInput"
          type="file"
          accept="application/json,.json"
          class="sr-only"
          aria-hidden="true"
          tabindex="-1"
          @change="onFileChosen"
        />

        <template v-if="configStore.pendingImport === null">
          <p class="m-0 text-[12px] leading-[1.6] text-signal-muted">
            Choose a file exported from another Sentry. Nothing is applied until you confirm.
          </p>
          <div>
            <BaseButton variant="ghost" :disabled="isBusy" @click="pickFile">
              Choose a configuration file…
            </BaseButton>
          </div>
        </template>

        <template v-else>
          <NoticeBox tone="info" role="status">
            <div class="flex flex-col gap-2">
              <p class="m-0">
                <strong class="font-semibold">{{ configStore.pendingFileName }}</strong> contains
                {{ configStore.pendingDeviceCount }}
                device {{ configStore.pendingDeviceCount === 1 ? 'entry' : 'entries'
                }}<template v-if="configStore.pendingHasHotspot">
                  and a hotspot configuration</template
                >.
              </p>
              <p class="m-0 text-[11px]">
                Devices are matched by their identity, so a dongle that is not plugged into this
                Sentry yet is reported and skipped rather than failing the import.
              </p>
            </div>
          </NoticeBox>

          <BaseToggle
            v-model="configStore.applyDevices"
            label="Apply device settings"
            accessible-name="Apply device settings from the file"
            :disabled="isBusy"
          />
          <BaseToggle
            v-if="configStore.pendingHasHotspot"
            v-model="configStore.applyHotspot"
            label="Apply hotspot settings"
            accessible-name="Apply hotspot settings from the file"
            :disabled="isBusy"
          />
          <p v-if="configStore.pendingHasHotspot" class="-mt-1 m-0 text-[11px] text-signal-muted">
            The file carries no password, so this writes the network’s settings but never starts it.
            A Sentry with no hotspot password stored will refuse until one is set.
          </p>

          <div class="flex flex-wrap gap-2">
            <BaseButton
              variant="primary"
              :disabled="isBusy || (!configStore.applyDevices && !configStore.applyHotspot)"
              @click="applyImport"
            >
              {{ isBusy ? 'Importing…' : 'Apply this configuration' }}
            </BaseButton>
            <BaseButton variant="ghost" :disabled="isBusy" @click="configStore.clearPendingImport">
              Cancel
            </BaseButton>
          </div>
        </template>

        <ConfigImportReport v-if="configStore.lastResult" :result="configStore.lastResult" />
      </section>

      <div>
        <BaseButton variant="ghost" :disabled="isBusy" @click="close">Close</BaseButton>
      </div>
    </div>
  </BaseDialog>
</template>
