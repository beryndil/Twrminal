import * as api from '$lib/api';
import type { MessageAttachment } from '$lib/api/sessions';
import { auth } from '$lib/stores/auth.svelte';
import { conversation } from '$lib/stores/conversation.svelte';
import { preferences } from '$lib/stores/preferences.svelte';
import { sessions } from '$lib/stores/sessions.svelte';
import { notify } from '$lib/utils/notify';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';
export type PermissionMode = 'default' | 'plan' | 'acceptEdits' | 'bypassPermissions';

const MAX_RETRY_DELAY_MS = 30_000;
const BASE_RETRY_DELAY_MS = 1_000;
const CODE_NORMAL_CLOSE = 1000;
const CODE_UNAUTHORIZED = 4401;
const CODE_SESSION_NOT_FOUND = 4404;
/** Grace period between a Stop-button click and the actual WS stop
 * frame leaving the browser. Long enough to react to an accidental
 * click (a stray mouse click on the red header button used to kill
 * an in-flight turn), short enough that a deliberate stop still
 * feels responsive. Every Stop click swaps the button for an inline
 * "Stopping Xs · Undo" pill (`StopUndoInline.svelte`) for this
 * window; if the user clicks Undo inside it, the frame never leaves
 * the browser and the agent keeps streaming. */
const STOP_DELAY_MS = 3_000;

/** Resolve on the next animation frame. Used in `connect()` to yield
 * the main thread after flipping the loading flag, so the browser can
 * actually paint the overlay spinner before the heavy render work
 * (REST fetch → Svelte re-render of the MessageTurn tree → shiki
 * syntax highlighting on each code block) pins the thread. SSR fallback
 * resolves immediately: there's no animation frame in node-side tests,
 * and the visual yield isn't relevant there anyway.
 *
 * Vitest's `vi.useFakeTimers()` stubs `requestAnimationFrame` with a
 * callback that never fires unless timers are advanced manually, which
 * would hang every test that `await`s `connect()`. The `import.meta.env.TEST`
 * branch short-circuits under vitest; there's no visible paint in jsdom
 * anyway, so nothing of value is lost. */
function waitForPaint(): Promise<void> {
  if (import.meta.env.TEST) return Promise.resolve();
  if (typeof requestAnimationFrame === 'undefined') return Promise.resolve();
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

/**
 * WebSocket connection to the active session's agent runner.
 *
 * Since v0.3, the server's agent runner is detached from the socket
 * lifetime — closing this connection no longer stops the agent. Every
 * event arrives with a monotonic `_seq`; the conversation store
 * remembers the highest seq seen per session and passes it back as
 * `since_seq` on reconnect so we replay only what we missed.
 *
 * Navigating to another session closes *this* socket but leaves the
 * old session's runner (and its in-flight turn) running on the server.
 * Returning to the old session reconnects with the stored seq and the
 * UI catches up.
 */
export class AgentConnection {
  state = $state<ConnectionState>('idle');
  sessionId = $state<string | null>(null);
  lastCloseCode = $state<number | null>(null);
  reconnectDelayMs = $state<number | null>(null);
  permissionMode = $state<PermissionMode>('default');
  /** Epoch-ms the Stop button was clicked; null when no stop is
   * pending. Drives the inline "Stopping in Xs — Undo" indicator
   * that replaces the Stop button during the STOP_DELAY_MS grace
   * window. Kept reactive so Conversation / ChecklistChat headers
   * can render the countdown next to where the user's cursor is. */
  stopPendingStartedAt = $state<number | null>(null);
  /** Grace window length in ms, exposed so the inline indicator can
   * compute its countdown without duplicating the constant. */
  readonly stopPendingWindowMs = STOP_DELAY_MS;

  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retryCount = 0;
  private wantConnected = false;
  // Deferred stop frame: a pending Stop-button click waiting out its
  // STOP_DELAY_MS grace period. Non-null means "a stop is queued,
  // don't enqueue another." Cleared by timer fire, by Undo click, or
  // by close() / session-switch.
  private pendingStopTimer: ReturnType<typeof setTimeout> | null = null;

  async connect(sessionId: string): Promise<void> {
    this.close();
    this.wantConnected = true;
    this.sessionId = sessionId;
    this.lastCloseCode = null;
    this.retryCount = 0;
    // Flip the per-session loading flag synchronously here (not inside
    // conversation.load) so the overlay spinner paints in the same
    // frame as the click, BEFORE the main thread gets pinned by
    // Svelte's first render of the new session's MessageTurn tree
    // (shiki syntax highlighting on many code blocks is the usual
    // culprit). The `await` on requestAnimationFrame below then yields
    // the thread so the browser can actually deliver that first paint
    // — without it, `conversation.load` would kick off immediately and
    // the spinner would only become visible in the eventual composite,
    // which for heavy sessions is after the "hang" the user reports.
    conversation.markLoadingInitial(sessionId, true);
    await waitForPaint();
    // Seed from the persisted column (migration 0012) so a reload or
    // cross-tab navigation restores Plan / Auto-edit / Bypass instead
    // of silently dropping to Ask. Falls back to 'default' when the
    // session has no stored mode or the fetch fails; the subsequent
    // openSocket → 'open' handler re-sends the remembered mode only
    // if it isn't 'default', so default stays a true no-op.
    const session = await conversation.load(sessionId);
    this.permissionMode = session?.permission_mode ?? 'default';
    this.openSocket(sessionId);
  }

  send(prompt: string, attachments: MessageAttachment[] = []): boolean {
    if (!this.socket || this.state !== 'open' || !this.sessionId) return false;
    // Optimistic user message carries the same attachment sidecar the
    // server is about to persist — the UI shows chips the instant the
    // user hits send rather than waiting for the next `/messages`
    // fetch. Empty array == plain text prompt; the server treats
    // missing and empty identically.
    conversation.pushUserMessage(this.sessionId, prompt, attachments);
    const frame: {
      type: 'prompt';
      content: string;
      attachments?: MessageAttachment[];
    } = { type: 'prompt', content: prompt };
    if (attachments.length > 0) frame.attachments = attachments;
    this.socket.send(JSON.stringify(frame));
    return true;
  }

  stop(): boolean {
    if (!this.socket || this.state !== 'open') return false;
    // Don't stack stops. If one is already queued behind its grace
    // window, the inline countdown pill is visible and the user can
    // either wait it out or Undo — a second click is a no-op rather
    // than shortening the window.
    if (this.pendingStopTimer !== null) return false;
    const socket = this.socket;
    // Flip the reactive "stop is pending" flag BEFORE scheduling the
    // timer so the Conversation / ChecklistChat headers swap their
    // Stop button for the inline countdown in the same tick. Paired
    // with the clear inside the timer below and in cancelPendingStop.
    this.stopPendingStartedAt = Date.now();
    this.pendingStopTimer = setTimeout(() => {
      this.pendingStopTimer = null;
      this.stopPendingStartedAt = null;
      // Re-check the socket the timer fires against — close() /
      // session-switch may have replaced it while the countdown ran.
      // We send on the socket that was live at click time, not the
      // current one, since the user clicked Stop on a specific
      // session's stream. If that socket is gone, the stop is moot.
      if (this.socket === socket && this.state === 'open') {
        socket.send(JSON.stringify({ type: 'stop' }));
      }
    }, STOP_DELAY_MS);
    return true;
  }

  /** Abort a Stop-button click before its grace period expires. Called
   * from the inline Undo button, from `close()` on session switch, and
   * from any future path that needs to un-queue a pending stop.
   * Idempotent — safe to call when nothing is pending. */
  cancelPendingStop(): void {
    if (this.pendingStopTimer !== null) {
      clearTimeout(this.pendingStopTimer);
      this.pendingStopTimer = null;
    }
    this.stopPendingStartedAt = null;
  }

  setPermissionMode(mode: PermissionMode): boolean {
    if (!this.socket || this.state !== 'open') return false;
    this.permissionMode = mode;
    this.socket.send(JSON.stringify({ type: 'set_permission_mode', mode }));
    return true;
  }

  /** Resolve a pending tool-use approval prompt. Clears the modal
   * optimistically via the conversation store; the server's matching
   * `approval_resolved` broadcast will arrive shortly after and be a
   * no-op thanks to the store's id check. Returns false when the
   * socket is not open — the modal stays visible and the user can
   * retry after reconnect (the backend Future is still parked).
   *
   * `updatedInput` is the UI-collected override forwarded to
   * `PermissionResultAllow.updated_input` on the backend so the SDK
   * invokes the tool with an enriched payload. The AskUserQuestion
   * modal uses this to inject collected `answers` into the original
   * `questions` input — without it, the tool runs with an empty
   * answer set and the agent sees "User has answered your questions:".
   * Ignored on deny; only meaningful when `decision === 'allow'`. */
  respondToApproval(
    requestId: string,
    decision: 'allow' | 'deny',
    reason?: string,
    updatedInput?: Record<string, unknown>
  ): boolean {
    if (!this.socket || this.state !== 'open' || !this.sessionId) return false;
    this.socket.send(
      JSON.stringify({
        type: 'approval_response',
        request_id: requestId,
        decision,
        ...(reason ? { reason } : {}),
        ...(updatedInput ? { updated_input: updatedInput } : {})
      })
    );
    conversation.clearPendingApproval(this.sessionId, requestId);
    return true;
  }

  close(): void {
    this.wantConnected = false;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectDelayMs = null;
    // Drop any pending stop — we're tearing down the socket it would
    // have targeted. The undo toast that was pushed alongside it
    // times out on its own; we don't need to evict it since its
    // inverse is now a harmless no-op (pendingStopTimer is null).
    this.cancelPendingStop();
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    this.state = 'idle';
  }

  private openSocket(sessionId: string): void {
    this.state = 'connecting';
    // Replay cursor: the conversation store tracks the highest `_seq`
    // seen for this session so the server can replay only what we
    // missed while the socket was down (or focus was elsewhere).
    const sinceSeq = conversation.lastSeqFor(sessionId);
    const ws = api.openAgentSocket(sessionId, sinceSeq);
    this.socket = ws;

    // Stale-socket guard. A previous socket's async close can schedule
    // a reconnect during the `await` gap in connect(), spawning a
    // parallel socket. Each listener below compares `this.socket` to
    // its captured `ws` so an orphan goes silent instead of double-
    // delivering every token event.
    const isCurrent = (): boolean => this.socket === ws;

    ws.addEventListener('open', () => {
      if (!isCurrent()) {
        ws.close();
        return;
      }
      this.state = 'open';
      this.retryCount = 0;
      this.reconnectDelayMs = null;
      // Reconnect persistence: the server-side SessionRunner resets to
      // `default` whenever a new WS attaches, so a drop → reconnect
      // silently downgrades a user who had picked `acceptEdits` or
      // `bypassPermissions`. Re-send the remembered mode the instant
      // the new socket is up so approval prompts don't resume behind
      // the user's back. `connect()` resets `permissionMode` to
      // `default`, so session-switch remains a clean slate — this
      // branch only fires for in-place reconnects.
      if (this.permissionMode !== 'default') {
        ws.send(
          JSON.stringify({
            type: 'set_permission_mode',
            mode: this.permissionMode
          })
        );
      }
    });

    ws.addEventListener('message', (msg) => {
      if (!isCurrent()) return;
      try {
        const event = JSON.parse(msg.data) as api.AgentEvent;
        // Snapshot the "is this a fresh completion" signal BEFORE the
        // reducer runs — once handleEvent returns the id is already
        // recorded in `completedMessageIds` either way, so a
        // post-hoc check can't tell a replay from a novel turn.
        const fresh =
          event.type === 'message_complete' &&
          !conversation
            .completedIdsFor(event.session_id)
            .has(event.message_id);
        conversation.handleEvent(event);
        if (fresh && event.type === 'message_complete') {
          maybeNotifyTurnComplete(event);
        }
      } catch (e) {
        conversation.error = e instanceof Error ? e.message : String(e);
      }
    });

    ws.addEventListener('close', (ev) => {
      if (!isCurrent()) return;
      this.state = 'closed';
      this.lastCloseCode = ev.code;
      this.socket = null;
      if (ev.code === CODE_UNAUTHORIZED) {
        auth.markInvalid();
        this.wantConnected = false;
        return;
      }
      if (this.shouldReconnect(ev.code)) {
        this.scheduleReconnect();
      }
    });

    ws.addEventListener('error', () => {
      if (!isCurrent()) return;
      this.state = 'error';
    });
  }

  private shouldReconnect(code: number): boolean {
    return (
      this.wantConnected &&
      code !== CODE_SESSION_NOT_FOUND &&
      code !== CODE_UNAUTHORIZED &&
      code !== CODE_NORMAL_CLOSE
    );
  }

  private scheduleReconnect(): void {
    if (!this.sessionId) return;
    const delay = Math.min(
      BASE_RETRY_DELAY_MS * 2 ** this.retryCount,
      MAX_RETRY_DELAY_MS
    );
    this.retryCount += 1;
    this.reconnectDelayMs = delay;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelayMs = null;
      // A fresh connect() during the delay may have already opened the
      // authoritative socket. Spawning a parallel one here is what
      // doubled every token event in v0.3.x.
      if (this.socket) return;
      if (this.wantConnected && this.sessionId) {
        this.openSocket(this.sessionId);
      }
    }, delay);
  }
}

export const agent = new AgentConnection();

/** Raise a tray notification for a completed agent turn when the
 * user has opted in via Settings and the tab is currently in the
 * background (hidden or unfocused). Staying silent for a focused
 * tab keeps the nicety from becoming noise for the common case
 * where the user is watching the reply stream in.
 *
 * Caller is responsible for filtering replayed `message_complete`
 * frames — the `fresh` snapshot at the WS listener handles that by
 * checking `completedIdsFor` BEFORE the reducer records the id. */
function maybeNotifyTurnComplete(event: api.MessageCompleteEvent): void {
  if (!preferences.notifyOnComplete) return;
  if (typeof document !== 'undefined') {
    const hidden = document.visibilityState === 'hidden';
    const unfocused =
      typeof document.hasFocus === 'function' && !document.hasFocus();
    if (!hidden && !unfocused) return;
  }
  const session = sessions.list.find((s) => s.id === event.session_id);
  const title = session?.title?.trim() || 'Untitled session';
  notify('Claude finished replying', {
    body: title,
    tag: `bearings:complete:${event.session_id}`
  });
}
