/**
 * Desktop notification utilities (gap-cycle-07-001).
 *
 * Consumers:
 *  - ``agent.svelte.ts`` calls :func:`maybeFireTurnNotification` on every
 *    ``message_complete`` WS event.
 *  - The Settings Notifications section calls
 *    :func:`requestNotifyPermission` before enabling the toggle, and
 *    :func:`supportsNotifications` to gate the UI.
 *
 * Module-level ``_notifyOnComplete`` is the single source of truth for the
 * opt-in value during the session.  :func:`setNotifyOnComplete` is called
 * by the Settings page on initial load and after every successful PATCH.
 */

/** Browser notification permission values (mirrors DOM NotificationPermission). */
export type NotifyPermission = "default" | "granted" | "denied";

let _notifyOnComplete = false;

/** True when the browser exposes the Notifications API. */
export function supportsNotifications(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/**
 * Update the module-level ``notify_on_complete`` preference.
 * Called by the Settings page on load and after every successful PATCH.
 */
export function setNotifyOnComplete(value: boolean): void {
  _notifyOnComplete = value;
}

/** Read the current module-level value (for tests and agent.svelte.ts). */
export function getNotifyOnComplete(): boolean {
  return _notifyOnComplete;
}

/**
 * Request browser notification permission.
 *
 * Returns the resulting :type:`NotifyPermission` string. Always returns
 * ``"denied"`` when the browser does not support notifications so callers
 * do not need to branch on :func:`supportsNotifications` separately.
 */
export async function requestNotifyPermission(): Promise<NotifyPermission> {
  if (!supportsNotifications()) return "denied";
  return Notification.requestPermission() as Promise<NotifyPermission>;
}

/**
 * Fire a desktop notification if all conditions hold:
 *
 * 1. ``_notifyOnComplete`` is ``true`` (the user opted in).
 * 2. The browser supports the Notifications API.
 * 3. ``Notification.permission === "granted"``.
 * 4. The document is hidden or unfocused
 *    (``document.visibilityState === "hidden" || !document.hasFocus()``).
 *
 * Fires ``new Notification("Bearings", { body: "Claude finished replying." })``.
 * No-ops silently when any condition is unmet — callers need no try/catch.
 */
export function maybeFireTurnNotification(): void {
  if (!_notifyOnComplete) return;
  if (!supportsNotifications()) return;
  if (Notification.permission !== "granted") return;
  if (document.visibilityState !== "hidden" && document.hasFocus()) return;
  new Notification("Bearings", { body: "Claude finished replying." });
}
