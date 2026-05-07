/**
 * Global store for transient shell-operation error notifications.
 *
 * Context-menu shell actions ("Open in editor", "Reveal in file
 * explorer", "Open in terminal") call ``POST /api/shell/exec`` and
 * must surface a user-visible message when the backend returns a
 * non-2xx response.  Because some of these actions fire from inside a
 * Svelte action (not a component), error state must live outside the
 * component tree.
 *
 * ``ShellOpNotification.svelte`` (mounted in ``+layout.svelte``)
 * observes this store and renders a dismiss-able banner when
 * ``message`` is non-null.
 *
 * Behavior anchor:
 * ``docs/behavior/context-menus.md`` §"Shell-open integration" — failure
 * modes.
 */

interface ShellOpNotificationState {
  /** Currently displayed error message, or ``null`` when hidden. */
  message: string | null;
}

const _state: ShellOpNotificationState = $state({ message: null });

/** Reactive notification state; read by ``ShellOpNotification.svelte``. */
export const shellOpNotificationStore = _state;

/**
 * Surface ``message`` as a transient toast.  Replaces any toast
 * already showing.
 */
export function showShellOpError(message: string): void {
  _state.message = message;
}

/** Dismiss the toast without any other side-effects. */
export function clearShellOpNotification(): void {
  _state.message = null;
}
