import * as api from '$lib/api';
import { conversation } from '$lib/stores/conversation.svelte';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

const MAX_RETRY_DELAY_MS = 30_000;
const BASE_RETRY_DELAY_MS = 1_000;
const CODE_NORMAL_CLOSE = 1000;
const CODE_SESSION_NOT_FOUND = 4404;

class AgentConnection {
  state = $state<ConnectionState>('idle');
  sessionId = $state<string | null>(null);
  lastCloseCode = $state<number | null>(null);
  reconnectDelayMs = $state<number | null>(null);

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
    await conversation.load(sessionId);
    this.openSocket(sessionId);
  }

  send(prompt: string): boolean {
    if (!this.socket || this.state !== 'open' || !this.sessionId) return false;
    conversation.pushUserMessage(this.sessionId, prompt);
    this.socket.send(JSON.stringify({ type: 'prompt', content: prompt }));
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
    const ws = api.openAgentSocket(sessionId);
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
