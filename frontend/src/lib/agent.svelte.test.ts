import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mocks resolve to top-level vi.fn() so `vi.mock` hoisting works with
// ESM. Modules under test import these indirectly.
const openAgentSocket = vi.fn<(sessionId: string, sinceSeq?: number) => FakeSocket>();
const handleEvent = vi.fn();
const conversationLoad = vi.fn<(sessionId: string) => Promise<void>>();
const pushUserMessage = vi.fn();

vi.mock('$lib/api', () => ({
  openAgentSocket: (sessionId: string, sinceSeq?: number) => openAgentSocket(sessionId, sinceSeq),
  onAuthFailure: vi.fn()
}));

vi.mock('$lib/stores/auth.svelte', () => ({
  auth: { markInvalid: vi.fn() }
}));

vi.mock('$lib/stores/conversation.svelte', () => ({
  conversation: {
    lastSeqFor: () => 0,
    load: (sessionId: string) => conversationLoad(sessionId),
    handleEvent: (...args: unknown[]) => handleEvent(...args),
    pushUserMessage: (...args: unknown[]) => pushUserMessage(...args),
    error: null
  }
}));

type Listener = (ev: unknown) => void;

// Minimal WebSocket stand-in. Only the API surface agent.svelte.ts
// actually calls is implemented — `addEventListener`, `close`, and the
// helpers used to drive events from tests.
class FakeSocket {
  readonly listeners: Record<string, Listener[]> = {};
  closed = false;
  constructor(public readonly sessionId: string) {}
  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }
  close(): void {
    this.closed = true;
  }
  fire(type: string, ev: unknown = {}): void {
    for (const l of this.listeners[type] ?? []) l(ev);
  }
  fireOpen(): void {
    this.fire('open');
  }
  fireMessage(data: unknown): void {
    this.fire('message', { data: JSON.stringify(data) });
  }
  fireClose(code = 1006): void {
    this.fire('close', { code });
  }
}

let sockets: FakeSocket[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  sockets = [];
  openAgentSocket.mockReset();
  handleEvent.mockReset();
  conversationLoad.mockReset();
  pushUserMessage.mockReset();
  openAgentSocket.mockImplementation((sessionId: string) => {
    const s = new FakeSocket(sessionId);
    sockets.push(s);
    return s;
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.resetModules();
});

async function freshAgent(): Promise<{ agent: { connect: (sid: string) => Promise<void> } }> {
  // Reimport per-test so each gets its own AgentConnection instance.
  vi.resetModules();
  const mod = await import('./agent.svelte');
  return { agent: new mod.AgentConnection() as unknown as { connect: (sid: string) => Promise<void> } };
}

describe('AgentConnection reconnect race', () => {
  it('does not double-deliver events when an old close fires during connect()', async () => {
    // Reproduces the v0.3.x doubling bug: during the `await
    // conversation.load()` gap in connect(), a prior socket's async
    // close event scheduled a reconnect, which raced with the legit
    // openSocket() call and spawned a parallel subscriber. Every
    // token event then fired handleEvent twice.
    const { agent } = await freshAgent();

    // First connect (resolve the awaited load so connect can finish).
    conversationLoad.mockResolvedValue();
    await agent.connect('A');
    expect(sockets.length).toBe(1);
    const s1 = sockets[0];
    s1.fireOpen();

    // Second connect races with s1's delayed close. connect() sets
    // wantConnected=true before awaiting load; we fire s1.close
    // DURING the await (while load is pending), which is the race.
    let resolveLoad = (): void => {};
    conversationLoad.mockImplementationOnce(
      () => new Promise<void>((resolve) => {
        resolveLoad = resolve;
      })
    );
    const connectPromise = agent.connect('A');
    // s1 is the now-orphaned socket from the first connect. Its async
    // close lands mid-await with a retryable code.
    s1.fireClose(1006);
    resolveLoad();
    await connectPromise;

    // openSocket ran once for the fresh connect.
    expect(sockets.length).toBe(2);
    const s2 = sockets[1];
    s2.fireOpen();

    // The orphan's scheduleReconnect timer fires ~1s later. Before the
    // fix this spawned a parallel socket (sockets.length → 3). After
    // the fix, it sees this.socket is set and bails.
    await vi.advanceTimersByTimeAsync(2000);
    expect(sockets.length).toBe(2);

    // Live event on the surviving socket delivers exactly once.
    s2.fireMessage({ type: 'token', session_id: 'A', text: 'Hel' });
    expect(handleEvent).toHaveBeenCalledTimes(1);

    // Any further message on the orphan (if it were still alive) must
    // not call handleEvent — the stale-socket identity guard suppresses
    // it even though the listener is still attached.
    s1.fireMessage({ type: 'token', session_id: 'A', text: 'ghost' });
    expect(handleEvent).toHaveBeenCalledTimes(1);
  });

  it('still reconnects normally when no competing connect is in flight', async () => {
    // Baseline: the stale-guard fix must not break the ordinary
    // server-went-away reconnect path.
    const { agent } = await freshAgent();

    conversationLoad.mockResolvedValue();
    await agent.connect('B');
    const s1 = sockets[0];
    s1.fireOpen();

    s1.fireClose(1006);
    await vi.advanceTimersByTimeAsync(2000);

    expect(sockets.length).toBe(2);
    const s2 = sockets[1];
    s2.fireOpen();
    s2.fireMessage({ type: 'token', session_id: 'B', text: 'x' });
    expect(handleEvent).toHaveBeenCalledTimes(1);
  });
});
