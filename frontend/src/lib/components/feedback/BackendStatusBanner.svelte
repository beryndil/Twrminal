<script lang="ts">
  /**
   * Backend-unreachable sticky banner (gap-cycle-01-006).
   *
   * Observable behavior: ``docs/behavior/chat.md`` §"Error states"
   * "Backend unreachable":
   *
   * - Hidden while the sessions-broadcast WebSocket is ``'open'``.
   * - Suppressed (no banner, no timer) when the socket closes with
   *   code 4401 (auth failure delegated to AuthGate).
   * - When the socket enters ``'closed'`` or ``'error'``, a
   *   :data:`BACKEND_UNREACHABLE_THRESHOLD_MS` grace period starts.
   *   If the socket recovers within that window the banner never
   *   appears; if not, the banner becomes visible.
   * - Clears immediately when the socket returns to ``'open'``.
   *
   * The grace period avoids flashing "Backend unreachable" on routine
   * server restarts or brief network blips that resolve in under 5 s.
   *
   * Mounted once in the app-shell layout (``+layout.svelte``). Rendered
   * as a ``position: fixed`` overlay so it does not disturb the
   * three-column grid layout.
   */
  import {
    BACKEND_STATUS_BANNER_STRINGS,
    BACKEND_UNREACHABLE_THRESHOLD_MS,
    WS_CLOSE_CODE_AUTH_FAILURE,
  } from "../../config";
  import { wsConnectionStatus } from "../../stores/sessions.svelte";

  /** Whether the banner is currently visible to the user. */
  let visible = $state(false);

  /**
   * Handle to the pending threshold timer, or ``null`` when no timer
   * is running. Cleared whenever the socket reconnects, an auth-failure
   * close suppresses the banner, or the timer fires and sets
   * ``visible = true``.
   */
  let thresholdTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    const wsState = wsConnectionStatus.state;
    const closeCode = wsConnectionStatus.lastCloseCode;

    if (wsState === "open") {
      // Reconnected — hide immediately and cancel any pending timer.
      if (thresholdTimer !== null) {
        clearTimeout(thresholdTimer);
        thresholdTimer = null;
      }
      visible = false;
      return;
    }

    if (closeCode === WS_CLOSE_CODE_AUTH_FAILURE) {
      // Auth failure — suppress banner; AuthGate owns this error state.
      if (thresholdTimer !== null) {
        clearTimeout(thresholdTimer);
        thresholdTimer = null;
      }
      visible = false;
      return;
    }

    // Socket is 'closed' or 'error' and not auth-suppressed.
    // Guard: don't stack timers; if one is already running or the
    // banner is already visible there is nothing left to do.
    if (thresholdTimer === null && !visible) {
      thresholdTimer = setTimeout(() => {
        thresholdTimer = null;
        visible = true;
      }, BACKEND_UNREACHABLE_THRESHOLD_MS);
    }

    // Cleanup: runs before the next $effect execution (on any reactive
    // dependency change) and on component unmount. Cancels an in-flight
    // timer so state transitions don't leave orphaned callbacks.
    return () => {
      if (thresholdTimer !== null) {
        clearTimeout(thresholdTimer);
        thresholdTimer = null;
      }
    };
  });
</script>

{#if visible}
  <div
    class="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-2 bg-amber-500/90 px-4 py-2 text-sm font-medium text-white backdrop-blur-sm"
    role="status"
    aria-live="polite"
    data-testid="backend-status-banner"
    aria-label={BACKEND_STATUS_BANNER_STRINGS.ariaLabel}
  >
    <span class="animate-pulse" aria-hidden="true">●</span>
    <span>{BACKEND_STATUS_BANNER_STRINGS.message}</span>
  </div>
{/if}
