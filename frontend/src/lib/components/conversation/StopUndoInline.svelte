<script lang="ts">
  /**
   * Inline stop-turn control — shown while an assistant turn is in
   * flight (i.e. the most recent assistant turn is incomplete).
   *
   * Clicking "■ Stop" calls ``POST /api/sessions/{id}/stop`` which
   * sets the runner's stop event. The SDK loop's watcher picks up the
   * edge and forwards ``client.interrupt()`` to the SDK subprocess.
   * The turn ends with a terminal ``MessageComplete`` or ``ErrorEvent``,
   * which the conversation store already handles.
   *
   * The button disables itself after the first click to prevent double-
   * submission while the SDK is unwinding. It re-enables if the
   * parent re-mounts (session switch resets state via ``sessionId``
   * prop change).
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"The agent loop
   * start/stop semantics" — the user can interrupt a running turn; the
   * SDK signals the subprocess to stop cleanly. No ``kill -TERM``
   * needed because ``client.interrupt()`` goes through the SDK's own
   * control channel.
   */
  import { stopSession } from "../../api/sessions";
  import { CONVERSATION_STRINGS } from "../../config";

  interface Props {
    sessionId: string;
  }

  const { sessionId }: Props = $props();

  let stopping = $state(false);

  async function handleStop(): Promise<void> {
    if (stopping) return;
    stopping = true;
    try {
      await stopSession(sessionId);
    } catch {
      // Best-effort: if the request fails (e.g. 404 race when the
      // session was just deleted), re-enable the button so the user
      // can retry or navigate away.
      stopping = false;
    }
  }
</script>

<div class="stop-inline flex items-center gap-2 px-4 py-2" data-testid="stop-inline">
  <button
    type="button"
    class="stop-inline__btn rounded bg-surface-2 px-3 py-1 text-xs font-medium text-fg-strong shadow transition-opacity hover:bg-surface-3 disabled:opacity-50"
    data-testid="stop-turn-button"
    disabled={stopping}
    aria-label={CONVERSATION_STRINGS.stopTurnAriaLabel}
    onclick={handleStop}
  >
    {CONVERSATION_STRINGS.stopTurnLabel}
  </button>
  {#if stopping}
    <span class="text-xs text-fg-muted" data-testid="stop-inline-stopping">Stopping…</span>
  {/if}
</div>
