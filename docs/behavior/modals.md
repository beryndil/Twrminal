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
