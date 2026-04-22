import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session } from '$lib/api';

// Mocks resolve to top-level vi.fn() so `vi.mock` hoisting works with
// ESM. Modules under test import these indirectly.
const openAgentSocket = vi.fn<(sessionId: string, sinceSeq?: number) => FakeSocket>();
const handleEvent = vi.fn();
// Real `conversation.load` returns `Promise<Session | null>` — the
// session is consumed by AgentConnection to seed the persisted
// permission_mode (migration 0012). Tests that don't care about that
// seeding resolve with null.
const conversationLoad = vi.fn<(sessionId: string) => Promise<Session | null>>();
const pushUserMessage = vi.fn();
const notifyMock = vi.fn();
const prefsState = { notifyOnComplete: false };
const sessionsList: Array<{ id: string; title: string | null }> = [];
const completedIds = new Map<string, Set<string>>();

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
    completedIdsFor: (sessionId: string) =>
      completedIds.get(sessionId) ?? new Set<string>(),
    error: null
  }
}));

vi.mock('$lib/stores/prefs.svelte', () => ({
  prefs: prefsState
}));

vi.mock('$lib/stores/sessions.svelte', () => ({
  sessions: {
    get list() {
      return sessionsList;
    }
  }
}));

vi.mock('$lib/utils/notify', () => ({
  notify: (...args: unknown[]) => notifyMock(...args)
}));

type Listener = (ev: unknown) => void;

// Minimal WebSocket stand-in. Only the API surface agent.svelte.ts
// actually calls is implemented — `addEventListener`, `close`, and the
// helpers used to drive events from tests.
class FakeSocket {
  readonly listeners: Record<string, Listener[]> = {};
  readonly sent: string[] = [];
  closed = false;
  constructor(public readonly sessionId: string) {}
  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }
  send(data: string): void {
    this.sent.push(data);
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
  notifyMock.mockReset();
  prefsState.notifyOnComplete = false;
  sessionsList.length = 0;
  completedIds.clear();
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

type TestAgent = {
  connect: (sid: string) => Promise<void>;
  setPermissionMode: (
    mode: 'default' | 'plan' | 'acceptEdits' | 'bypassPermissions'
  ) => boolean;
  permissionMode: 'default' | 'plan' | 'acceptEdits' | 'bypassPermissions';
};

/** Minimal Session factory for seeding `conversation.load` mocks. Only
 * the fields AgentConnection consumes (`permission_mode`) matter for
 * the assertions; everything else is filled with innocuous defaults
 * so the shape stays valid against the real Session type. */
function fakeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 'S',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    working_dir: '/tmp',
    model: 'claude-opus-4-7',
    title: null,
    description: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 0,
    session_instructions: null,
    permission_mode: null,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    closed_at: null,
    kind: 'chat',
    ...overrides
  };
}

async function freshAgent(): Promise<{ agent: TestAgent }> {
  // Reimport per-test so each gets its own AgentConnection instance.
  vi.resetModules();
  const mod = await import('./agent.svelte');
  return { agent: new mod.AgentConnection() as unknown as TestAgent };
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
    conversationLoad.mockResolvedValue(null);
    await agent.connect('A');
    expect(sockets.length).toBe(1);
    const s1 = sockets[0];
    s1.fireOpen();

    // Second connect races with s1's delayed close. connect() sets
    // wantConnected=true before awaiting load; we fire s1.close
    // DURING the await (while load is pending), which is the race.
    let resolveLoad = (): void => {};
    conversationLoad.mockImplementationOnce(
      () => new Promise<Session | null>((resolve) => {
        resolveLoad = () => resolve(null);
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

    conversationLoad.mockResolvedValue(null);
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

describe('AgentConnection turn-complete notifications', () => {
  it('fires notify() on a fresh message_complete when opted in and tab is hidden', async () => {
    const { agent } = await freshAgent();
    conversationLoad.mockResolvedValue(null);
    await agent.connect('N');
    const s = sockets[0];
    s.fireOpen();

    prefsState.notifyOnComplete = true;
    sessionsList.push({ id: 'N', title: 'Bearings dev' });
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden'
    });

    s.fireMessage({
      type: 'message_complete',
      session_id: 'N',
      message_id: 'msg-1',
      cost_usd: 0
    });

    expect(notifyMock).toHaveBeenCalledWith(
      'Claude finished replying',
      expect.objectContaining({ body: 'Bearings dev', tag: 'bearings:complete:N' })
    );
  });

  it('does not fire when the opt-in pref is off', async () => {
    const { agent } = await freshAgent();
    conversationLoad.mockResolvedValue(null);
    await agent.connect('N');
    const s = sockets[0];
    s.fireOpen();

    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden'
    });

    s.fireMessage({
      type: 'message_complete',
      session_id: 'N',
      message_id: 'msg-1',
      cost_usd: 0
    });

    expect(notifyMock).not.toHaveBeenCalled();
  });

  it('skips replayed message_complete frames (already in completedIds)', async () => {
    const { agent } = await freshAgent();
    conversationLoad.mockResolvedValue(null);
    await agent.connect('N');
    const s = sockets[0];
    s.fireOpen();

    prefsState.notifyOnComplete = true;
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden'
    });
    // Pretend the reducer already recorded this message_id — a
    // reconnect replay delivers the same frame and must NOT retrigger
    // the notification.
    completedIds.set('N', new Set(['msg-1']));

    s.fireMessage({
      type: 'message_complete',
      session_id: 'N',
      message_id: 'msg-1',
      cost_usd: 0
    });

    expect(notifyMock).not.toHaveBeenCalled();
  });
});

describe('AgentConnection permission-mode persistence', () => {
  it('re-sends the selected permission mode when a reconnect completes', async () => {
    // The server-side runner resets permission mode whenever a new WS
    // attaches, so a drop → reconnect would silently downgrade the user
    // from (e.g.) bypassPermissions back to default and the next tool
    // call would surface an approval prompt they thought they'd
    // waived. This asserts the client pushes the remembered mode on
    // the fresh socket's open event.
    const { agent } = await freshAgent();

    conversationLoad.mockResolvedValue(null);
    await agent.connect('C');
    const s1 = sockets[0];
    s1.fireOpen();

    agent.setPermissionMode('bypassPermissions');
    expect(s1.sent).toContainEqual(
      JSON.stringify({
        type: 'set_permission_mode',
        mode: 'bypassPermissions'
      })
    );

    s1.fireClose(1006);
    await vi.advanceTimersByTimeAsync(2000);

    const s2 = sockets[1];
    s2.fireOpen();

    // The freshly opened socket must carry the remembered mode in its
    // very first send, before the user can issue any prompt.
    expect(s2.sent).toContainEqual(
      JSON.stringify({
        type: 'set_permission_mode',
        mode: 'bypassPermissions'
      })
    );
  });

  it('does not push a set_permission_mode frame on reconnect when mode is default', async () => {
    // No-op guard: avoid spamming the server with redundant frames when
    // the user never left the default mode. Catches a naive
    // implementation that always re-sends.
    const { agent } = await freshAgent();

    conversationLoad.mockResolvedValue(null);
    await agent.connect('D');
    const s1 = sockets[0];
    s1.fireOpen();

    s1.fireClose(1006);
    await vi.advanceTimersByTimeAsync(2000);

    const s2 = sockets[1];
    s2.fireOpen();

    expect(s2.sent).toEqual([]);
  });

  it('seeds permissionMode from session.permission_mode on connect', async () => {
    // Migration 0012: the server persists the user's last-picked
    // PermissionMode on the sessions row. Opening a session that had
    // 'plan' stored must start the selector on 'plan' — not 'default'
    // — and re-push that mode on the fresh socket's open event so the
    // runner starts the next turn in the right state.
    const { agent } = await freshAgent();

    conversationLoad.mockResolvedValue(fakeSession({ permission_mode: 'plan' }));
    await agent.connect('E');
    expect(agent.permissionMode).toBe('plan');

    const s1 = sockets[0];
    s1.fireOpen();
    expect(s1.sent).toContainEqual(
      JSON.stringify({ type: 'set_permission_mode', mode: 'plan' })
    );
  });

  it('falls back to default when session.permission_mode is null', async () => {
    // Pre-migration-0012 sessions store NULL, new sessions start NULL
    // too. Both must render as 'default' without pushing a frame on
    // open, same as the no-session-found path.
    const { agent } = await freshAgent();

    conversationLoad.mockResolvedValue(fakeSession({ permission_mode: null }));
    await agent.connect('F');
    expect(agent.permissionMode).toBe('default');

    const s1 = sockets[0];
    s1.fireOpen();
    expect(s1.sent).toEqual([]);
  });
});
