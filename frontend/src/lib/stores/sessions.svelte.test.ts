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
    message_count: 2,
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

  it('treats missing `closed_at` (undefined) as open — defensive against a backend that omits the field', () => {
    // Cast through `unknown` to bypass the Session type guard. This
    // shape lands in the wild during a rolling deploy where the
    // frontend bundle ships before the backend picks up migration
    // 0015 — the field is simply absent from the payload.
    const partial = {
      id: 'no-field',
      created_at: '2026-04-21T00:00:00+00:00',
      updated_at: '2026-04-21T00:00:00+00:00',
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
      last_context_max: null
      // closed_at intentionally absent
    };
    sessions.list = [partial as unknown as Session];
    expect(sessions.openList.map((s) => s.id)).toEqual(['no-field']);
    expect(sessions.closedList).toEqual([]);
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

describe('sessions.scrollTick', () => {
  it('touchSession on the selected id increments the tick', () => {
    sessions.list = [
      sess({ id: 'sess-a' }),
      sess({ id: 'sess-b', updated_at: '2026-04-20T00:00:00+00:00' })
    ];
    sessions.selectedId = 'sess-b';
    const before = sessions.scrollTick;
    sessions.touchSession('sess-b');
    expect(sessions.scrollTick).toBe(before + 1);
    // And the row actually moved to the top.
    expect(sessions.list[0].id).toBe('sess-b');
  });

  it('touchSession on a non-selected id leaves the tick alone', () => {
    sessions.list = [
      sess({ id: 'sess-a' }),
      sess({ id: 'sess-b', updated_at: '2026-04-20T00:00:00+00:00' })
    ];
    sessions.selectedId = 'sess-a';
    const before = sessions.scrollTick;
    sessions.touchSession('sess-b');
    // Reorder still happens — the sidebar viewport just doesn't snap.
    expect(sessions.list[0].id).toBe('sess-b');
    expect(sessions.scrollTick).toBe(before);
  });

  it('touchSession on an unknown id is a no-op (no tick, no reorder)', () => {
    sessions.list = [sess({ id: 'sess-a' })];
    sessions.selectedId = 'sess-a';
    const before = sessions.scrollTick;
    sessions.touchSession('does-not-exist');
    expect(sessions.scrollTick).toBe(before);
    expect(sessions.list.map((s) => s.id)).toEqual(['sess-a']);
  });

  it('bumpCost on the selected id increments the tick', () => {
    sessions.list = [
      sess({ id: 'sess-a' }),
      sess({ id: 'sess-b', updated_at: '2026-04-20T00:00:00+00:00' })
    ];
    sessions.selectedId = 'sess-b';
    const before = sessions.scrollTick;
    sessions.bumpCost('sess-b', 0.05);
    expect(sessions.scrollTick).toBe(before + 1);
    expect(sessions.list[0].id).toBe('sess-b');
    expect(sessions.list[0].total_cost_usd).toBeCloseTo(0.05);
  });

  it('bumpCost on a non-selected id leaves the tick alone', () => {
    sessions.list = [
      sess({ id: 'sess-a' }),
      sess({ id: 'sess-b', updated_at: '2026-04-20T00:00:00+00:00' })
    ];
    sessions.selectedId = 'sess-a';
    const before = sessions.scrollTick;
    sessions.bumpCost('sess-b', 0.05);
    expect(sessions.list[0].id).toBe('sess-b');
    expect(sessions.scrollTick).toBe(before);
  });
});

describe('sessions.softRefresh', () => {
  it('reorders rows when the server reports newer activity on a background session', async () => {
    // Local order: a (newest) on top, b underneath. While the user sits
    // on a, session b runs in the background — the server's updated_at
    // on b now beats a, so softRefresh should float b to the top.
    sessions.list = [
      sess({ id: 'a', updated_at: '2026-04-22T10:00:00+00:00' }),
      sess({ id: 'b', updated_at: '2026-04-22T09:00:00+00:00' })
    ];
    sessions.selectedId = 'a';
    queueResponses([
      {
        ok: true,
        body: [
          sess({ id: 'b', updated_at: '2026-04-22T11:00:00+00:00' }),
          sess({ id: 'a', updated_at: '2026-04-22T10:00:00+00:00' })
        ]
      }
    ]);
    await sessions.softRefresh();
    expect(sessions.list.map((s) => s.id)).toEqual(['b', 'a']);
    expect(sessions.selectedId).toBe('a');
  });

  it('keeps the local row when local updated_at is strictly newer than server', async () => {
    // Optimistic touchSession fired locally; server hasn't caught up.
    // softRefresh must not drop the row back down and then snap it up
    // on the next tick.
    sessions.list = [
      sess({ id: 'a', updated_at: '2026-04-22T12:00:00.500+00:00', total_cost_usd: 0.42 }),
      sess({ id: 'b', updated_at: '2026-04-22T12:00:00+00:00' })
    ];
    queueResponses([
      {
        ok: true,
        body: [
          sess({ id: 'a', updated_at: '2026-04-22T12:00:00+00:00', total_cost_usd: 0.11 }),
          sess({ id: 'b', updated_at: '2026-04-22T12:00:00+00:00' })
        ]
      }
    ]);
    await sessions.softRefresh();
    expect(sessions.list.map((s) => s.id)).toEqual(['a', 'b']);
    // Local optimistic row survives the reconcile.
    expect(sessions.list[0].total_cost_usd).toBeCloseTo(0.42);
  });

  it('takes server state when server updated_at is newer or equal', async () => {
    // Equal timestamps prefer the server row so server-authoritative
    // fields (cost, message_count) converge without needing a bump.
    sessions.list = [
      sess({ id: 'a', updated_at: '2026-04-22T12:00:00+00:00', total_cost_usd: 0.0 })
    ];
    queueResponses([
      {
        ok: true,
        body: [
          sess({ id: 'a', updated_at: '2026-04-22T12:00:00+00:00', total_cost_usd: 0.99 })
        ]
      }
    ]);
    await sessions.softRefresh();
    expect(sessions.list[0].total_cost_usd).toBeCloseTo(0.99);
  });

  it('adds newly-created sessions and drops rows the server no longer returns', async () => {
    sessions.list = [
      sess({ id: 'stale', updated_at: '2026-04-22T08:00:00+00:00' }),
      sess({ id: 'keep', updated_at: '2026-04-22T09:00:00+00:00' })
    ];
    queueResponses([
      {
        ok: true,
        body: [
          sess({ id: 'fresh', updated_at: '2026-04-22T10:00:00+00:00' }),
          sess({ id: 'keep', updated_at: '2026-04-22T09:00:00+00:00' })
        ]
      }
    ]);
    await sessions.softRefresh();
    expect(sessions.list.map((s) => s.id)).toEqual(['fresh', 'keep']);
  });

  it('clears selectedId when the selected session vanishes from the server list', async () => {
    sessions.list = [sess({ id: 'gone' }), sess({ id: 'other' })];
    sessions.selectedId = 'gone';
    queueResponses([{ ok: true, body: [sess({ id: 'other' })] }]);
    await sessions.softRefresh();
    expect(sessions.selectedId).toBeNull();
    expect(sessions.list.map((s) => s.id)).toEqual(['other']);
  });

  it('keeps the running set intact — softRefresh is not responsible for badges', async () => {
    sessions.list = [sess({ id: 'a' })];
    sessions.running = new Set(['a']);
    queueResponses([{ ok: true, body: [sess({ id: 'a' })] }]);
    await sessions.softRefresh();
    expect(sessions.running.has('a')).toBe(true);
  });

  it('swallows transport errors — the next tick retries', async () => {
    sessions.list = [sess({ id: 'a' })];
    queueResponses([{ ok: false, status: 503, body: 'service unavailable' }]);
    await sessions.softRefresh();
    // List untouched, no error raised.
    expect(sessions.list.map((s) => s.id)).toEqual(['a']);
    expect(sessions.error).toBeNull();
  });

  it('forwards the active filter to the server fetch', async () => {
    sessions.filter = { tags: [7, 9], mode: 'all' };
    sessions.list = [];
    const capturedUrls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string | URL | Request) => {
        capturedUrls.push(String(url));
        return {
          ok: true,
          status: 200,
          async json() {
            return [];
          },
          async text() {
            return '[]';
          }
        };
      })
    );
    await sessions.softRefresh();
    expect(capturedUrls).toHaveLength(1);
    expect(capturedUrls[0]).toContain('tags=7%2C9');
    expect(capturedUrls[0]).toContain('mode=all');
  });
});

describe('sessions.applyUpsert', () => {
  it('inserts a brand-new session and sorts it by updated_at DESC, id DESC', () => {
    sessions.list = [sess({ id: 'a', updated_at: '2026-04-22T10:00:00+00:00' })];
    sessions.applyUpsert(
      sess({ id: 'b', updated_at: '2026-04-22T11:00:00+00:00' })
    );
    expect(sessions.list.map((s) => s.id)).toEqual(['b', 'a']);
  });

  it('replaces an existing row when server updated_at is newer', () => {
    sessions.list = [
      sess({ id: 'a', updated_at: '2026-04-22T10:00:00+00:00', total_cost_usd: 0 })
    ];
    sessions.applyUpsert(
      sess({ id: 'a', updated_at: '2026-04-22T11:00:00+00:00', total_cost_usd: 1.23 })
    );
    expect(sessions.list[0].total_cost_usd).toBeCloseTo(1.23);
  });

  it('keeps the local row when local updated_at is strictly newer (optimistic touch)', () => {
    sessions.list = [
      sess({ id: 'a', updated_at: '2026-04-22T11:00:01+00:00', total_cost_usd: 0.42 })
    ];
    sessions.applyUpsert(
      sess({ id: 'a', updated_at: '2026-04-22T11:00:00+00:00', total_cost_usd: 0.11 })
    );
    // Local optimistic row survives the broadcast.
    expect(sessions.list[0].total_cost_usd).toBeCloseTo(0.42);
  });

  it('preserves the final sort on a re-sort after an upsert that bumps a middle row', () => {
    sessions.list = [
      sess({ id: 'a', updated_at: '2026-04-22T12:00:00+00:00' }),
      sess({ id: 'b', updated_at: '2026-04-22T11:00:00+00:00' }),
      sess({ id: 'c', updated_at: '2026-04-22T10:00:00+00:00' })
    ];
    sessions.applyUpsert(
      sess({ id: 'c', updated_at: '2026-04-22T13:00:00+00:00' })
    );
    expect(sessions.list.map((s) => s.id)).toEqual(['c', 'a', 'b']);
  });

  it('is a no-op when a tag filter is active — softRefresh poll reconciles filtered views', () => {
    sessions.filter = { tags: [42] };
    sessions.list = [sess({ id: 'existing' })];
    sessions.applyUpsert(sess({ id: 'new-row' }));
    expect(sessions.list.map((s) => s.id)).toEqual(['existing']);
  });
});

describe('sessions.applyDelete', () => {
  it('drops the row and clears selectedId when the deleted session was selected', () => {
    sessions.list = [sess({ id: 'a' }), sess({ id: 'b' })];
    sessions.selectedId = 'a';
    sessions.applyDelete('a');
    expect(sessions.list.map((s) => s.id)).toEqual(['b']);
    expect(sessions.selectedId).toBeNull();
  });

  it('preserves selectedId when a different session is deleted', () => {
    sessions.list = [sess({ id: 'a' }), sess({ id: 'b' })];
    sessions.selectedId = 'a';
    sessions.applyDelete('b');
    expect(sessions.list.map((s) => s.id)).toEqual(['a']);
    expect(sessions.selectedId).toBe('a');
  });

  it('is a no-op on an unknown id', () => {
    sessions.list = [sess({ id: 'a' })];
    sessions.applyDelete('not-there');
    expect(sessions.list.map((s) => s.id)).toEqual(['a']);
  });
});

describe('sessions.applyRunnerState', () => {
  it('adds an id to the running set when is_running is true', () => {
    sessions.running = new Set();
    sessions.applyRunnerState('a', true);
    expect(sessions.running.has('a')).toBe(true);
  });

  it('removes an id from the running set when is_running is false', () => {
    sessions.running = new Set(['a', 'b']);
    sessions.applyRunnerState('a', false);
    expect(sessions.running.has('a')).toBe(false);
    expect(sessions.running.has('b')).toBe(true);
  });

  it('reassigns the Set (not in-place mutation) so Svelte 5 consumers re-read', () => {
    const before = sessions.running;
    sessions.applyRunnerState('a', true);
    expect(sessions.running).not.toBe(before);
  });

  it('applyRunnerState=false on an id not in the set is a no-op', () => {
    sessions.running = new Set(['a']);
    sessions.applyRunnerState('not-there', false);
    expect(sessions.running.has('a')).toBe(true);
    expect(sessions.running.size).toBe(1);
  });
});

