import * as api from '$lib/api';
import { auth } from '$lib/stores/auth.svelte';
import { conversation } from '$lib/stores/conversation.svelte';
import { prefs } from '$lib/stores/prefs.svelte';
import { sessions } from '$lib/stores/sessions.svelte';
import { notify } from '$lib/utils/notify';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';
export type PermissionMode = 'default' | 'plan' | 'acceptEdits' | 'bypassPermissions';

const MAX_RETRY_DELAY_MS = 30_000;
const BASE_RETRY_DELAY_MS = 1_000;
const CODE_NORMAL_CLOSE = 1000;
const CODE_UNAUTHORIZED = 4401;
const CODE_SESSION_NOT_FOUND = 4404;

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

  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retryCount = 0;
  private wantConnected = false;

  async connect(sessionId: string): Promise<void> {
    this.close();
    this.wantConnected = true;
    this.sessionId = sessionId;
    this.lastCloseCode = null;
    this.retryCount = 0;
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

  send(prompt: string): boolean {
    if (!this.socket || this.state !== 'open' || !this.sessionId) return false;
    conversation.pushUserMessage(this.sessionId, prompt);
    this.socket.send(JSON.stringify({ type: 'prompt', content: prompt }));
    return true;
  }

  stop(): boolean {
    if (!this.socket || this.state !== 'open') return false;
    this.socket.send(JSON.stringify({ type: 'stop' }));
    return true;
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
   * retry after reconnect (the backend Future is still parked). */
  respondToApproval(
    requestId: string,
    decision: 'allow' | 'deny',
    reason?: string
  ): boolean {
    if (!this.socket || this.state !== 'open' || !this.sessionId) return false;
    this.socket.send(
      JSON.stringify({
        type: 'approval_response',
        request_id: requestId,
        decision,
        ...(reason ? { reason } : {})
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
  if (!prefs.notifyOnComplete) return;
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
