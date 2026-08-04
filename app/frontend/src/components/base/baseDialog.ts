import { el, setAttribute } from '../../core/dom.js'
import type { Child } from '../../core/dom.js'
import type { Component } from '../../core/component.js'
import { createFocusTrap } from '../../core/focusTrap.js'
import { syncChildren } from './childrenSync.js'

/**
 * The single accessible modal primitive every dialog in the app composes
 * from — owns focus-trapping, `Escape`-to-dismiss, and restoring focus to
 * whichever control opened it (via `createFocusTrap`), so no dialog has to
 * reimplement modal semantics itself. Callers provide the id of their own
 * heading via `labelledBy` and their body as `children`.
 *
 * Visually the panel is a settings card scaled up (Sentinel `.settings-item`):
 * square, flat panel fill, 22px padding, over a blurred black scrim.
 *
 * `disableDismiss` suppresses `Escape` (and the caller is expected to also
 * disable its own close/cancel controls) while a destructive action is
 * already committed and in flight, so a stray keypress can never read as
 * "cancelling" hardware that is already being written to.
 *
 * Teleport equivalent: the retired `.vue` version rendered `<Teleport
 * to="body">`. This factory reproduces that itself — the overlay is appended
 * directly to `document.body` while `open` is true rather than into wherever
 * the caller's own tree lives, and removed again when it closes or the
 * component is destroyed. Callers must NOT additionally append `.element`
 * into their own DOM tree.
 */
export interface BaseDialogProps {
  open: boolean
  labelledBy: string
  disableDismiss?: boolean
  onClose: () => void
  children: Child[]
}

const OVERLAY_CLASSES =
  'fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm'

const PANEL_CLASSES =
  'flex max-h-full w-full max-w-lg flex-col gap-4 overflow-y-auto rounded-rack bg-ground-panel p-card outline-none'

/** Builds a `BaseDialog`. `update` mutates the same panel in place and mounts/unmounts it from `document.body` as `open` changes. */
export function baseDialog(props: BaseDialogProps): Component<BaseDialogProps> {
  let currentProps = props
  let isMountedToBody = false

  const panel = el(
    'div',
    {
      attrs: {
        role: 'dialog',
        'aria-modal': 'true',
        'aria-labelledby': props.labelledBy,
        tabindex: -1,
      },
      class: PANEL_CLASSES,
    },
    props.children,
  )

  const overlay = el('div', { class: OVERLAY_CLASSES }, [panel])

  const focusTrap = createFocusTrap({
    panel,
    onRequestClose: () => currentProps.onClose(),
    isDismissSuppressed: () => currentProps.disableDismiss ?? false,
  })

  function applyOpenState(open: boolean): void {
    if (open === isMountedToBody) {
      return
    }
    isMountedToBody = open
    if (open) {
      document.body.appendChild(overlay)
      focusTrap.activate()
    } else {
      focusTrap.release()
      overlay.remove()
    }
  }

  applyOpenState(props.open)

  return {
    // The overlay is teleported to `document.body` by this factory itself
    // (see the doc comment above); this reference exists for API consistency
    // and so `destroy` can find the node, not for a caller to append.
    element: overlay,

    update(nextProps): void {
      currentProps = nextProps
      setAttribute(panel, 'aria-labelledby', nextProps.labelledBy)
      syncChildren(panel, nextProps.children)
      applyOpenState(nextProps.open)
    },

    destroy(): void {
      focusTrap.release()
      overlay.remove()
    },
  }
}
