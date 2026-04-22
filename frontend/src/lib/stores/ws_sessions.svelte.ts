import * as api from '$lib/api';
import { auth } from '$lib/stores/auth.svelte';
import { sessions } from '$lib/stores/sessions.svelte';

/**
 * Broadcast subscriber for the server-wide sessions-list WS channel.
 *
 * Unlike `AgentConnection` this socket is not per-session — it's one
 * connection per tab that streams `upsert | delete | runner_state`
 * frames for every session in the UI. Pairs with
 * `SessionsBroker` on the backend.
 *
 * Why both this AND the Phase-1 softRefresh poll? The broadcast is the
 * live path: sub-second latency, no list-sized fetch per tick. The
 * poll stays as a belt-and-suspenders reconcile — if a broker
 * publisher drops a slow subscriber, or the socket bounces, the
 * next poll converges the list within 3 s. Once the broadcast has
 * earned trust (metrics, uptime), the poll can be removed.
 *
 * Reconnect matches `AgentConnection`: exponential backoff capped at
 * 30 s. On connect (fresh or reconnect) we fire one `softRefresh` so
 * any events missed while down are reconciled in one shot — the
 * broker has no replay buffer because the poll already is one.
 */

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

const MAX_RETRY_DELAY_MS = 30_000;
const BASE_RETRY_DELAY_MS = 1_000;
const CODE_NORMAL_CLOSE = 1000;
const CODE_UNAUTHORIZED = 4401;

type UpsertFrame = { kind: 'upsert'; session: api.Session };
type DeleteFrame = { kind: 'delete'; session_id: string };
type RunnerStateFrame = { kind: 'runner_state'; session_id: string; is_running: boolean };
type SessionsWsFrame = UpsertFrame | DeleteFrame | RunnerStateFrame;

class SessionsWsConnection {
  state = $state<ConnectionState>('idle');
  lastCloseCode = $state<number | null>(null);

  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retryCount = 0;
  private wantConnected = false;
  private openSocketImpl: () => WebSocket;

  constructor(openSocketImpl: () => WebSocket = api.openSessionsSocket) {
    this.openSocketImpl = openSocketImpl;
  }

  connect(): void {
    if (this.wantConnected && this.socket) return;
    this.wantConnected = true;
    this.retryCount = 0;
    this.lastCloseCode = null;
    this.openSocket();
  }

  close(): void {
    this.wantConnected = false;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    this.state = 'idle';
  }

  /** Apply a received frame to the sessions store. Exposed so tests
   * can exercise the reducer without spinning up a WebSocket. */
  handleFrame(frame: SessionsWsFrame): void {
    if (frame.kind === 'upsert') {
      sessions.applyUpsert(frame.session);
    } else if (frame.kind === 'delete') {
      sessions.applyDelete(frame.session_id);
    } else if (frame.kind === 'runner_state') {
      sessions.applyRunnerState(frame.session_id, frame.is_running);
    }
  }

  private openSocket(): void {
    this.state = 'connecting';
    const ws = this.openSocketImpl();
    this.socket = ws;

    const isCurrent = (): boolean => this.socket === ws;

    ws.addEventListener('open', () => {
      if (!isCurrent()) {
        ws.close();
        return;
      }
      this.state = 'open';
      this.retryCount = 0;
      // Reconcile once on every successful open (fresh or reconnect)
      // so anything missed while down is picked up in one shot.
      // Silent on failure — the next poll tick catches it.
      void sessions.softRefresh();
    });

    ws.addEventListener('message', (msg) => {
      if (!isCurrent()) return;
      try {
        const frame = JSON.parse(msg.data) as SessionsWsFrame;
        this.handleFrame(frame);
      } catch {
        // Malformed frame — drop it. A persistent problem surfaces as
        // an increasingly stale sidebar, which the poll tick repairs.
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
      this.wantConnected && code !== CODE_UNAUTHORIZED && code !== CODE_NORMAL_CLOSE
    );
  }

  private scheduleReconnect(): void {
    const delay = Math.min(
      BASE_RETRY_DELAY_MS * 2 ** this.retryCount,
      MAX_RETRY_DELAY_MS
    );
    this.retryCount += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      // Avoid spawning a parallel socket if a caller already reopened.
      if (this.socket) return;
      if (this.wantConnected) this.openSocket();
    }, delay);
  }
}

export const sessionsWs = new SessionsWsConnection();
// Exported class so tests can inject a socket factory.
export { SessionsWsConnection };
