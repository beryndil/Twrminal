/**
 * Auth-gate store (gap-cycle-01-007).
 *
 * Tracks whether the application is in a "blocking" auth-required state
 * and provides :func:`saveToken` to exit it.
 *
 * Observable behavior: ``docs/behavior/chat.md`` §"Error states"
 * "Auth required / token expired".
 *
 * Trigger wiring: this store deliberately has no side effects and does
 * NOT subscribe to ``wsConnectionStatus`` directly.  The cross-store
 * wiring lives in ``AuthGate.svelte`` via its ``$effect`` block, per
 * the architecture rule that components (not stores) own cross-store
 * dependencies — stores never subscribe to each other.
 */
import { AUTH_TOKEN_STORAGE_KEY } from "../config";

interface AuthState {
  /**
   * When ``true``, the :class:`AuthGate` modal blocks all interaction
   * until a valid token is submitted.
   *
   * Set to ``true`` by :func:`_setBlocking` (called from
   * ``AuthGate.svelte``'s ``$effect`` when the broadcast WS closes with
   * code 4401).  Cleared to ``false`` by :func:`saveToken` on success.
   */
  blocking: boolean;
}

const state: AuthState = $state({ blocking: false });

/** Reactive auth state — components read ``authStore.blocking``. */
export const authStore: AuthState = state;

/**
 * Set the ``blocking`` flag.
 *
 * Called exclusively by ``AuthGate.svelte`` when it detects the WS
 * auth-failure close code.  Kept as a named function (rather than a
 * direct store mutation) so the write path is auditable and mockable
 * in tests.
 *
 * @param v - ``true`` to open the gate; ``false`` to close it.
 */
export function _setBlocking(v: boolean): void {
  state.blocking = v;
}

/**
 * Persist ``value`` as the active auth token and clear the blocking gate.
 *
 * The token is stored under :data:`AUTH_TOKEN_STORAGE_KEY` in
 * ``localStorage`` (same namespace as other per-device Bearings
 * preferences).  Clearing ``blocking`` is unconditional after the
 * write: if the token turns out to be invalid the backend will close the
 * next WebSocket with code 4401, which causes ``AuthGate``'s ``$effect``
 * to set ``blocking`` again.
 *
 * @param value - Raw token string from the input; leading/trailing
 *   whitespace is stripped before persisting.
 */
export async function saveToken(value: string): Promise<void> {
  localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, value.trim());
  state.blocking = false;
}

// ---- Test helpers -----------------------------------------------------------

/**
 * Reset auth store to its initial state between tests.
 *
 * Clears ``blocking`` and removes the token from ``localStorage``.
 * Call in ``afterEach`` alongside ``window.localStorage.clear()``.
 */
export function _resetForTests(): void {
  state.blocking = false;
  localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

/**
 * Directly set ``blocking`` in unit tests without going through the WS
 * trigger.
 *
 * Used by ``AuthGate.test.ts`` to control component visibility without
 * needing a live WebSocket.
 */
export function _setBlockingForTests(v: boolean): void {
  state.blocking = v;
}
