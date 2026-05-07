# Modals — observable behavior

Covers standalone modal dialogs that are not part of the context-menu
overlay system. For context-menu confirmation dialogs see
[context-menus.md](context-menus.md) §"Destructive entries".

## ConfirmDialog focus

`ConfirmDialog` (`frontend/src/lib/components/sidebar/ConfirmDialog.svelte`)
manages focus on open based on the `destructive` prop:

* **`destructive=true` (default):** focus lands on the **Cancel** button
  immediately after mount. A stray Enter press cancels rather than
  confirming the destructive action. All current callers (delete session,
  delete message, delete tag, etc.) use this default.

* **`destructive=false`:** focus lands on the **Confirm** button. Intended
  for informational confirms where the action is safe and keyboard-confirm
  without mouse travel is desirable.

Focus is queued via `queueMicrotask` inside `onMount` so any pending
Svelte DOM changes are fully settled before `.focus()` is called.

Pressing Esc from either button calls `onCancel` (handled by the dialog's
`onkeydown` handler). Tab cycles between the two buttons per browser
native focus order.

## ConfirmDialog async pending

`onConfirm` (and `onConfirmAndSuppress`) may return a `Promise<void>`. The
dialog handles the in-flight state internally:

* **Buttons disabled**: both Cancel and Confirm are `disabled` while the
  promise is in flight, preventing double-submission. Esc and backdrop
  clicks are also suppressed during this window.
* **Confirm label**: flips to `"…"` (`CONTEXT_MENU_STRINGS.confirmPendingLabel`)
  while pending, giving the user immediate feedback for slow operations.
* **On resolve**: pending state clears. The parent owns closing the dialog
  (its `onConfirm` callback is the commit point — closing the dialog IS the
  normal resolution path).
* **On rejection**: pending state clears, both buttons re-enable, and the
  error message is surfaced inline below the dialog message via a
  `role="alert"` paragraph (`data-testid="confirm-dialog-error"`). The
  dialog stays open so the user can retry or cancel.

Synchronous `onConfirm` callbacks (`() => void`) work unchanged — `await`
on a non-Promise value resolves in the same microtask.
