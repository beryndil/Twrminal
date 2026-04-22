/**
 * Tests for SessionsWsConnection — the broadcast subscriber for the
 * server-wide `/ws/sessions` channel introduced in Phase 2.
 *
 * We exercise the frame reducer directly via `handleFrame` so we don't
 * need to spin up a real WebSocket. The class exposes `handleFrame`
 * explicitly for this reason.
 */

import { afterEach, describe, expect, it } from 'vitest';

import type { Session } from '$lib/api';
import { sessions } from './sessions.svelte';
import { SessionsWsConnection } from './ws_sessions.svelte';

afterEach(() => {
  sessions.list = [];
  sessions.selectedId = null;
  sessions.running = new Set();
  sessions.filter = {};
});

function sess(overrides: Partial<Session> = {}): Session {
  return {
    id: 'sess-a',
    created_at: '2026-04-21T00:00:00+00:00',
    updated_at: '2026-04-21T00:00:00+00:00',
    working_dir: '/tmp/a',
    model: 'claude-opus-4-7',
    title: 'Alpha',
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
    checklist_item_id: null,
    last_completed_at: null,
    last_viewed_at: null,
    tag_ids: [],
    ...overrides
  };
}

describe('SessionsWsConnection.handleFrame', () => {
  // A fake factory keeps the tests off the real network — the ctor
  // still requires one even though we never call connect() here.
  const fakeSocketFactory = () => new EventTarget() as unknown as WebSocket;

  it('upsert frame patches the sessions store list and re-sorts', () => {
    sessions.list = [sess({ id: 'a', updated_at: '2026-04-22T10:00:00+00:00' })];
    const conn = new SessionsWsConnection(fakeSocketFactory);
    conn.handleFrame({
      kind: 'upsert',
      session: sess({ id: 'b', updated_at: '2026-04-22T11:00:00+00:00' })
    });
    expect(sessions.list.map((s) => s.id)).toEqual(['b', 'a']);
  });

  it('delete frame drops the row and clears a matching selection', () => {
    sessions.list = [sess({ id: 'a' }), sess({ id: 'b' })];
    sessions.selectedId = 'a';
    const conn = new SessionsWsConnection(fakeSocketFactory);
    conn.handleFrame({ kind: 'delete', session_id: 'a' });
    expect(sessions.list.map((s) => s.id)).toEqual(['b']);
    expect(sessions.selectedId).toBeNull();
  });

  it('runner_state frame mutates the running set', () => {
    sessions.running = new Set();
    const conn = new SessionsWsConnection(fakeSocketFactory);
    conn.handleFrame({ kind: 'runner_state', session_id: 'a', is_running: true });
    expect(sessions.running.has('a')).toBe(true);
    conn.handleFrame({ kind: 'runner_state', session_id: 'a', is_running: false });
    expect(sessions.running.has('a')).toBe(false);
  });
});
