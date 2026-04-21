/**
 * Tests for the SessionStore's open/closed split and the close/reopen
 * methods introduced in v0.3.25. The derived `openList` / `closedList`
 * back the SessionList sidebar's two-bucket rendering, and the
 * close/reopen methods patch the row in-place so the UI re-renders
 * without a full `/api/sessions` refresh.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Session } from '$lib/api';
import { sessions } from './sessions.svelte';

afterEach(() => {
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
  sessions.loading = false;
  sessions.error = null;
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
    message_count: 2,
    session_instructions: null,
    permission_mode: null,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    closed_at: null,
    ...overrides
  };
}

type Fake = { ok: boolean; status?: number; body: unknown };

function queueResponses(queue: Fake[]): void {
  let i = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      const r = queue[i++];
      if (!r) throw new Error(`unexpected fetch call #${i}`);
      return {
        ok: r.ok,
        status: r.status ?? (r.ok ? 200 : 500),
        async json() {
          return r.body;
        },
        async text() {
          return typeof r.body === 'string' ? r.body : JSON.stringify(r.body);
        }
      };
    })
  );
}

describe('sessions store open/closed split', () => {
  it('openList and closedList partition `list` by closed_at', () => {
    sessions.list = [
      sess({ id: 'a', closed_at: null }),
      sess({ id: 'b', closed_at: '2026-04-20T00:00:00+00:00' }),
      sess({ id: 'c', closed_at: null }),
      sess({ id: 'd', closed_at: '2026-04-19T00:00:00+00:00' })
    ];
    expect(sessions.openList.map((s) => s.id)).toEqual(['a', 'c']);
    expect(sessions.closedList.map((s) => s.id)).toEqual(['b', 'd']);
  });

  it('both lists are empty when `list` is empty', () => {
    sessions.list = [];
    expect(sessions.openList).toEqual([]);
    expect(sessions.closedList).toEqual([]);
  });

  it('openList preserves the input ordering (store feeds it updated_at DESC)', () => {
    sessions.list = [
      sess({ id: 'newest', updated_at: '2026-04-21T12:00:00+00:00' }),
      sess({ id: 'middle', updated_at: '2026-04-21T06:00:00+00:00' }),
      sess({ id: 'oldest', updated_at: '2026-04-20T00:00:00+00:00' })
    ];
    expect(sessions.openList.map((s) => s.id)).toEqual(['newest', 'middle', 'oldest']);
  });
});

describe('sessions.close', () => {
  it('POSTs /close and patches the row with the returned closed_at', async () => {
    sessions.list = [sess({ id: 'sess-a', closed_at: null })];
    const closedAt = '2026-04-21T10:00:00+00:00';
    queueResponses([
      {
        ok: true,
        body: { ...sess({ id: 'sess-a' }), closed_at: closedAt }
      }
    ]);
    const result = await sessions.close('sess-a');
    expect(result?.closed_at).toBe(closedAt);
    expect(sessions.list[0].closed_at).toBe(closedAt);
    expect(sessions.error).toBeNull();
    // After the patch the derived lists swap the row into `closedList`.
    expect(sessions.openList).toEqual([]);
    expect(sessions.closedList.map((s) => s.id)).toEqual(['sess-a']);
  });

  it('records error text and leaves the row unchanged on failure', async () => {
    sessions.list = [sess({ id: 'sess-a', closed_at: null })];
    queueResponses([{ ok: false, status: 404, body: 'session not found' }]);
    const result = await sessions.close('sess-a');
    expect(result).toBeNull();
    expect(sessions.error).toContain('404');
    expect(sessions.list[0].closed_at).toBeNull();
  });

  it('is a no-op on an unknown id (no row to patch, still returns the server row)', async () => {
    sessions.list = [sess({ id: 'sess-a', closed_at: null })];
    const closedAt = '2026-04-21T10:00:00+00:00';
    queueResponses([
      { ok: true, body: { ...sess({ id: 'sess-b' }), closed_at: closedAt } }
    ]);
    await sessions.close('sess-b');
    // sess-a is untouched because the map() key didn't match.
    expect(sessions.list.map((s) => s.id)).toEqual(['sess-a']);
    expect(sessions.list[0].closed_at).toBeNull();
  });
});

describe('sessions.reopen', () => {
  it('POSTs /reopen and clears closed_at on the cached row', async () => {
    sessions.list = [
      sess({ id: 'sess-a', closed_at: '2026-04-20T00:00:00+00:00' })
    ];
    queueResponses([
      { ok: true, body: { ...sess({ id: 'sess-a' }), closed_at: null } }
    ]);
    const result = await sessions.reopen('sess-a');
    expect(result?.closed_at).toBeNull();
    expect(sessions.list[0].closed_at).toBeNull();
    expect(sessions.openList.map((s) => s.id)).toEqual(['sess-a']);
    expect(sessions.closedList).toEqual([]);
  });

  it('records error text on failure', async () => {
    sessions.list = [
      sess({ id: 'sess-a', closed_at: '2026-04-20T00:00:00+00:00' })
    ];
    queueResponses([{ ok: false, status: 500, body: 'boom' }]);
    const result = await sessions.reopen('sess-a');
    expect(result).toBeNull();
    expect(sessions.error).toContain('500');
    // Row unchanged.
    expect(sessions.list[0].closed_at).toBe('2026-04-20T00:00:00+00:00');
  });
});
