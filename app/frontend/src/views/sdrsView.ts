import { apiClient } from '../api/client.js'
import { emptyState } from '../components/base/emptyState.js'
import { panelStack } from '../components/base/panelStack.js'
import { forgetDeviceDialog } from '../components/device/forgetDeviceDialog.js'
import { sdrDeviceCard, type SdrDeviceCardProps } from '../components/device/sdrDeviceCard.js'
import { noticeList } from '../components/sdrs/noticeList.js'
import { absentDeviceGroup } from '../components/sdrs/absentDeviceGroup.js'
import {
  serialConflictBanner,
  type SerialConflictBannerProps,
} from '../components/serial/serialConflictBanner.js'
import { keyedList } from '../core/component.js'
import { el, ref, setVisible } from '../core/dom.js'
import { liveAnnouncer } from '../core/liveAnnouncer.js'
import { watchStore } from '../core/observable.js'
import {
  absentConfiguredDevices,
  closeForgetDialog,
  closeSerialFlashDialog,
  devices,
  forgetDialogDevice,
  openSerialFlashDialog,
  presentDevices,
  sdrsStore,
  serialConflictGroups,
} from '../state/sdrsStore.js'

import type { DeviceStatus } from '../api/client.js'

/**
 * The device list — everything inside `<main>`.
 *
 * Mounts into the containers `index.html` already declares (`data-ref`
 * `notice-list`, `serial-conflicts`, `device-list`), rather than building the
 * page scaffolding itself: the shell never changes shape, so it stays as markup.
 *
 * Returns a teardown function. There is one of these per page load, so it is
 * only ever called by tests.
 */
export function mountSdrsView(root: ParentNode): () => void {
  const { announcePolite, announceAssertive } = liveAnnouncer()

  const noticeContainer = ref(root, 'notice-list', HTMLElement)
  const conflictContainer = ref(root, 'serial-conflicts', HTMLUListElement)
  const deviceContainer = ref(root, 'device-list', HTMLElement)

  const notices = noticeList()
  noticeContainer.appendChild(notices.element)

  // Locally dismissed conflict banners, keyed by serial — dismissing hides the
  // summary banner without touching each affected card's own
  // needs-identification notice, and it reappears if the underlying conflict
  // changes shape (a new device joins it, etc.) since only the exact serial
  // dismissed is suppressed.
  const dismissedConflictSerials = new Set<string>()

  const conflictList = keyedList<SerialConflictBannerProps, string>(
    conflictContainer,
    (bannerProps) => {
      const listItem = el('li')
      const banner = serialConflictBanner(bannerProps)
      listItem.appendChild(banner.element)
      return {
        element: listItem,
        update: (nextProps) => banner.update(nextProps),
        destroy: () => banner.destroy(),
      }
    },
    (bannerProps) => bannerProps.serial,
  )

  // The three mutually exclusive states of the list: nothing detected at all,
  // everything configured but absent, or a stack of present devices.
  const noDevicesEmptyState = emptyState({
    title: 'No devices detected',
    detail: 'Connect an SDR to a USB port on this Pi.',
  })
  const allAbsentEmptyState = emptyState({
    title: 'No devices currently plugged in',
    detail: 'Every configured device below is absent — see the collapsed group beneath.',
  })
  const presentStack = panelStack({ children: [] })
  const presentCards = keyedList<SdrDeviceCardProps, string>(
    presentStack.element,
    sdrDeviceCard,
    (cardProps) => cardProps.device.device_id,
  )
  const absentGroup = absentDeviceGroup({
    devices: [],
    onRequestSerialFlash: openSerialFlashDialog,
  })

  deviceContainer.append(
    noDevicesEmptyState.element,
    allAbsentEmptyState.element,
    presentStack.element,
    absentGroup.element,
  )

  // `baseDialog` mounts itself on `document.body`, so this element is never
  // appended — only kept so `update` and `destroy` can reach it.
  const forgetDialog = forgetDeviceDialog({ device: null, onClose: closeForgetDialog })

  // Announce plug/unplug and state transitions (architecture §9.4) by diffing
  // each snapshot against the previous one's `(present, state)` pair.
  const previousDeviceSnapshot = new Map<string, { present: boolean; state: string }>()

  function announceTransitions(currentDevices: DeviceStatus[]): void {
    for (const device of currentDevices) {
      const previous = previousDeviceSnapshot.get(device.device_id)
      const label = device.name || device.device_id
      if (!previous) {
        if (device.present) {
          announcePolite(`${label} connected, now ${device.state}.`)
        }
      } else if (previous.state !== device.state || previous.present !== device.present) {
        if (device.state === 'error') {
          announceAssertive(
            `${label} error${device.state_reason ? `: ${device.state_reason}` : ''}.`,
          )
        } else if (!device.present && previous.present) {
          announcePolite(`${label} disconnected.`)
        } else {
          announcePolite(`${label} now ${device.state}.`)
        }
      }
      previousDeviceSnapshot.set(device.device_id, {
        present: device.present,
        state: device.state,
      })
    }
    for (const knownId of previousDeviceSnapshot.keys()) {
      if (!currentDevices.some((device) => device.device_id === knownId)) {
        previousDeviceSnapshot.delete(knownId)
      }
    }
  }

  const unsubscribe = watchStore(sdrsStore, (state) => {
    const allDevices = devices(state)
    const present = presentDevices(state)
    const absent = absentConfiguredDevices(state)

    announceTransitions(allDevices)

    const visibleConflicts = serialConflictGroups(state).filter(
      (group) => !dismissedConflictSerials.has(group.serial),
    )
    conflictContainer.hidden = visibleConflicts.length === 0
    conflictList.update(
      visibleConflicts.map((group) => ({
        serial: group.serial,
        conflictingDevices: group.devices,
        onDismiss: () => {
          dismissedConflictSerials.add(group.serial)
          // The store is the render trigger, and nothing about it changed —
          // re-run the same effect against current state to hide the banner.
          sdrsStore.setState({})
        },
        onRequestSerialFlash: openSerialFlashDialog,
      })),
    )

    setVisible(noDevicesEmptyState.element, allDevices.length === 0)
    setVisible(allAbsentEmptyState.element, allDevices.length > 0 && present.length === 0)
    setVisible(presentStack.element, present.length > 0)
    setVisible(absentGroup.element, absent.length > 0)

    presentCards.update(
      present.map((device) => ({ device, onRequestSerialFlash: openSerialFlashDialog })),
    )
    absentGroup.update({ devices: absent, onRequestSerialFlash: openSerialFlashDialog })
    forgetDialog.update({ device: forgetDialogDevice(state), onClose: closeForgetDialog })
  })

  // Port constraints are a convenience fetch: the SSE `snapshot` still
  // populates the devices without it, and constraints simply stay advisory-only
  // until it lands.
  void apiClient
    .listDevices()
    .then((devicesResponse) => {
      sdrsStore.setState({ constraints: devicesResponse.constraints })
    })
    .catch(() => {
      /* Advisory only — see above. */
    })

  return () => {
    unsubscribe()
    conflictList.destroy()
    presentCards.destroy()
    absentGroup.destroy()
    presentStack.destroy()
    noDevicesEmptyState.destroy()
    allAbsentEmptyState.destroy()
    forgetDialog.destroy()
    notices.destroy()
    closeSerialFlashDialog()
  }
}
