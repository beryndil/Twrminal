import * as api from '$lib/api';
import { auth } from '$lib/stores/auth.svelte';
import { conversation } from '$lib/stores/conversation.svelte';

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
class AgentConnection {
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
    this.permissionMode = 'default';
    await conversation.load(sessionId);
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

    ws.addEventListener('open', () => {
      this.state = 'open';
      this.retryCount = 0;
      this.reconnectDelayMs = null;
    });

    ws.addEventListener('message', (msg) => {
      try {
        const event = JSON.parse(msg.data) as api.AgentEvent;
        conversation.handleEvent(event);
      } catch (e) {
        conversation.error = e instanceof Error ? e.message : String(e);
      }
    });

    ws.addEventListener('close', (ev) => {
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
      if (this.wantConnected && this.sessionId) {
        this.openSocket(this.sessionId);
      }
    }, delay);
  }
}

export const agent = new AgentConnection();
