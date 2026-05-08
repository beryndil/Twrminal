<script lang="ts">
  /**
   * Inline stop-turn control — shown while an assistant turn is in
   * flight (i.e. the most recent assistant turn is incomplete).
   *
   * Grace-window behavior (gap-cycle-11-002):
   * Clicking "■ Stop" arms a ``STOP_UNDO_GRACE_MS`` grace window
   * instead of POSTing ``/stop`` immediately. While the window is open,
   * the Stop button is replaced (same DOM slot, no layout shift) with a
   * countdown chip ("Stopping Ns", ticking at ``STOP_UNDO_TICK_MS``
   * cadence) and an "Undo" button. Clicking Undo cancels the pending
   * stop — the turn continues uninterrupted and no ``/stop`` POST is
   * issued. When the grace window expires without Undo, a single
   * ``POST /api/sessions/{id}/stop`` fires and the chip disappears.
   *
   * Session-switch during a pending stop: the stop commits for the old
   * session (safer default — the user already asked for it; silently
   * discarding would be surprising). Implemented via the ``$effect``
   * cleanup that runs before Svelte re-evaluates the reactive dependency
   * on ``sessionId``, and again on component unmount.
   *
   * Double-click guard: ``handleStop`` exits early when ``pendingStop``
   * is already true. The Stop button is also hidden while the grace
   * window is active, making a structural second click impossible.
   *
   * Behavior anchor: ``docs/behavior/chat.md``
   * §"Stopping or interrupting a turn".
   */
  import { stopSession } from "../../api/sessions";
  import { CONVERSATION_STRINGS, STOP_UNDO_GRACE_MS, STOP_UNDO_TICK_MS } from "../../config";

  interface Props {
    sessionId: string;
  }

  const { sessionId }: Props = $props();

  // ── Grace-window state ────────────────────────────────────────────────

  /** True while the grace window is open (Stop clicked, Undo still possible). */
  let pendingStop = $state(false);
  /** Milliseconds remaining in the grace window; feeds the countdown chip. */
  let msLeft = $state(STOP_UNDO_GRACE_MS);

  let commitHandle: ReturnType<typeof setTimeout> | null = null;
  let tickHandle: ReturnType<typeof setInterval> | null = null;

  function clearTimers(): void {
    if (commitHandle !== null) {
      clearTimeout(commitHandle);
      commitHandle = null;
    }
    if (tickHandle !== null) {
      clearInterval(tickHandle);
      tickHandle = null;
    }
  }

  /**
   * Fire ``POST /api/sessions/{id}/stop`` and clean up grace-window state.
   * Called by either the grace-window ``setTimeout`` or the ``$effect``
   * cleanup on session-switch / unmount.
   */
  async function commitStop(id: string): Promise<void> {
    clearTimers();
    pendingStop = false;
    try {
      await stopSession(id);
    } catch {
      // Best-effort: if /stop fails after the grace window expires the
      // SDK runner may have already cleaned up on its own. Nothing
      // actionable to surface — the turn will eventually settle.
    }
  }

  /**
   * Handle the "■ Stop" button click: arm the grace window instead of
   * posting immediately.
   */
  function handleStop(): void {
    if (pendingStop) return; // double-click guard — already armed
    const capturedId = sessionId; // capture at arm time; safe across switches
    pendingStop = true;
    msLeft = STOP_UNDO_GRACE_MS;

    tickHandle = setInterval(() => {
      msLeft = Math.max(0, msLeft - STOP_UNDO_TICK_MS);
    }, STOP_UNDO_TICK_MS);

    commitHandle = setTimeout(() => {
      void commitStop(capturedId);
    }, STOP_UNDO_GRACE_MS);
  }

  /** Handle the "Undo" button click: cancel the pending stop. */
  function handleUndo(): void {
    clearTimers();
    pendingStop = false;
  }

  // Commit any pending stop when ``sessionId`` changes (session switch) or
  // when the component unmounts. Decision: commit is the safer default —
  // the user already asked for a stop; silently discarding it on a switch
  // would be surprising.
  //
  // The ``$effect`` creates a reactive dependency on ``sessionId`` only.
  // Reading ``pendingStop`` inside the returned cleanup closure does NOT
  // register an additional dependency (the cleanup runs imperatively, not
  // inside a reactive tracking context).
  $effect(() => {
    const capturedId = sessionId; // reactive — re-runs when sessionId changes
    return () => {
      clearTimers();
      if (pendingStop) {
        void commitStop(capturedId);
      }
    };
  });

  /** Seconds remaining, ceiled for display ("Stopping 3s", not "2.5s"). */
  const secondsLeft = $derived(Math.ceil(msLeft / 1000));
</script>

{#if pendingStop}
  <div class="stop-inline flex items-center gap-2 px-4 py-2" data-testid="stop-inline">
    <!--
      aria-live="polite" so screen readers announce each tick update
      without interrupting ongoing speech.
    -->
    <span
      class="stop-inline__countdown text-xs text-fg-muted tabular-nums"
      data-testid="stop-undo-countdown"
      aria-live="polite"
    >
      Stopping {secondsLeft}s
    </span>
    <button
      type="button"
      class="stop-inline__undo rounded bg-surface-2 px-3 py-1 text-xs font-medium text-fg-strong shadow transition-opacity hover:bg-surface-3"
      data-testid="stop-undo-button"
      aria-label={CONVERSATION_STRINGS.stopUndoAriaLabel}
      onclick={handleUndo}
    >
      {CONVERSATION_STRINGS.stopUndoLabel}
    </button>
  </div>
{:else}
  <div class="stop-inline flex items-center gap-2 px-4 py-2" data-testid="stop-inline">
    <button
      type="button"
      class="stop-inline__btn rounded bg-surface-2 px-3 py-1 text-xs font-medium text-fg-strong shadow transition-opacity hover:bg-surface-3"
      data-testid="stop-turn-button"
      aria-label={CONVERSATION_STRINGS.stopTurnAriaLabel}
      onclick={handleStop}
    >
      {CONVERSATION_STRINGS.stopTurnLabel}
    </button>
  </div>
{/if}
