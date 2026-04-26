/**
 * Tests for the SessionStore's open/closed split and the close/reopen
 * methods introduced in v0.3.25. The derived `openList` / `closedList`
 * back the SessionList sidebar's two-bucket rendering, and the
 * close/reopen methods patch the row in-place so the UI re-renders
 * without a full `/api/sessions` refresh.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session } from '$lib/api';
import { drafts } from './drafts.svelte';
import { sessions } from './sessions.svelte';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
  sessions.loading = false;
  sessions.error = null;
  sessions.running = new Set();
  sessions.awaiting = new Set();
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
    tag_ids: [],
    pinned: false,
    error_pending: false,
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

  it('preserves per-row object identity when the server reports no change', async () => {
    // Per-row identity has to survive a no-op poll. `sessions.selected`
    // is `$derived(this.list.find(...))`, and the form-seed effect in
    // SessionEdit, the autofocus effect in ChecklistView, and the
    // paired-crumb resolver in ConversationHeader all depend on
    // `selected` not changing identity unless something real changed.
    // If softRefresh ever returns a structurally-identical-but-new
    // object for an unchanged row, those effects re-fire on every 3 s
    // poll tick and clobber user input / steal focus / hammer
    // /checklist endpoints.
    const seed = sess({
      id: 'stable',
      updated_at: '2026-04-22T09:00:00+00:00',
      total_cost_usd: 0.5
    });
    sessions.list = [seed];
    // Capture the post-assignment proxy reference, not the raw seed —
    // Svelte 5 wraps `$state` array elements in fine-grained reactive
    // proxies, so the in-list reference is what consumers actually
    // observe via `sessions.list[0]` / `find(...)`.
    const stableRef = sessions.list[0];
    queueResponses([{ ok: true, body: [{ ...seed }] }]);
    await sessions.softRefresh();
    expect(sessions.list[0]).toBe(stableRef);
  });

  it('does not reassign sessions.list when every row is unchanged', async () => {
    // Companion to the per-row-identity test: even with all references
    // preserved, reassigning the array itself would still trip Svelte's
    // array-level reactivity for any consumer that reads
    // `sessions.list` directly. Skip the assignment when nothing moved.
    const a = sess({ id: 'a', updated_at: '2026-04-22T09:00:00+00:00' });
    const b = sess({ id: 'b', updated_at: '2026-04-22T08:00:00+00:00' });
    sessions.list = [a, b];
    const beforeArray = sessions.list;
    queueResponses([{ ok: true, body: [{ ...a }, { ...b }] }]);
    await sessions.softRefresh();
    expect(sessions.list).toBe(beforeArray);
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

  it('applies a server close even when local updated_at is strictly newer', async () => {
    // Regression for the "session closed but the sidebar still shows it
    // open under a tag filter" bug (2026-04-24). A recent bumpCost /
    // touchSession stamps updated_at from the client clock, which can
    // drift past the server's close timestamp — especially since the
    // Python `+00:00` suffix sorts below JS's `Z` for identical-instant
    // values. Without the lifecycle carve-out, the strict `updated_at >`
    // merge rule keeps the local (still-open) copy forever and the 3s
    // poll never converges. Lifecycle transitions from the server must
    // land regardless of which side's updated_at is newer.
    sessions.filter = { tags: [2] };
    sessions.list = [
      sess({
        id: 'stale-open',
        tag_ids: [2],
        updated_at: '2026-04-24T15:45:00.000+00:00',
        closed_at: null,
      }),
    ];
    queueResponses([
      {
        ok: true,
        body: [
          sess({
            id: 'stale-open',
            tag_ids: [2],
            updated_at: '2026-04-24T15:40:16.000000+00:00',
            closed_at: '2026-04-24T15:40:16.000000+00:00',
          }),
        ],
      },
    ]);
    await sessions.softRefresh();
    expect(sessions.list[0].closed_at).toBe('2026-04-24T15:40:16.000000+00:00');
  });

  it('applies a server reopen even when local updated_at is strictly newer', async () => {
    // Symmetric reopen case — local thinks the session is closed, server
    // was reopened by another tab. Lifecycle must flip regardless of
    // updated_at comparison.
    sessions.list = [
      sess({
        id: 'stale-closed',
        updated_at: '2026-04-24T16:00:00.000+00:00',
        closed_at: '2026-04-24T15:40:16.000000+00:00',
      }),
    ];
    queueResponses([
      {
        ok: true,
        body: [
          sess({
            id: 'stale-closed',
            updated_at: '2026-04-24T15:55:00.000000+00:00',
            closed_at: null,
          }),
        ],
      },
    ]);
    await sessions.softRefresh();
    expect(sessions.list[0].closed_at).toBeNull();
  });

  it('forwards the active filter to the server fetch', async () => {
    // v0.7.4 dropped the `mode=all` wire tag along with the Any/All
    // toggle. The tag filter is OR-only on the server now, so the
    // URL just carries `tags=...` — no mode component.
    sessions.filter = { tags: [7, 9] };
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
    expect(capturedUrls[0]).not.toContain('mode=');
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

  it('applies a server close even when local updated_at is strictly newer', () => {
    // Same carve-out as softRefresh — the WS upsert frame delivering a
    // close must flip lifecycle regardless of optimistic local bumps.
    sessions.list = [
      sess({
        id: 'a',
        updated_at: '2026-04-24T15:45:00.000+00:00',
        closed_at: null,
      }),
    ];
    sessions.applyUpsert(
      sess({
        id: 'a',
        updated_at: '2026-04-24T15:40:16.000000+00:00',
        closed_at: '2026-04-24T15:40:16.000000+00:00',
      })
    );
    expect(sessions.list[0].closed_at).toBe('2026-04-24T15:40:16.000000+00:00');
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

  it('applies an upsert whose tag_ids intersect the active filter', () => {
    sessions.filter = { tags: [42] };
    sessions.list = [
      sess({ id: 'existing', tag_ids: [42], updated_at: '2026-04-22T10:00:00+00:00' })
    ];
    sessions.applyUpsert(
      sess({
        id: 'existing',
        tag_ids: [42],
        updated_at: '2026-04-22T11:00:00+00:00',
        total_cost_usd: 2.5
      })
    );
    expect(sessions.list).toHaveLength(1);
    expect(sessions.list[0].total_cost_usd).toBeCloseTo(2.5);
  });

  it('drops an upsert whose tag_ids do not intersect the active filter (new row)', () => {
    sessions.filter = { tags: [42] };
    sessions.list = [sess({ id: 'existing', tag_ids: [42] })];
    sessions.applyUpsert(sess({ id: 'new-row', tag_ids: [99] }));
    expect(sessions.list.map((s) => s.id)).toEqual(['existing']);
  });

  it('inserts a brand-new row under a tag filter when its tag_ids share a tag with the filter', () => {
    sessions.filter = { tags: [42] };
    sessions.list = [
      sess({ id: 'existing', tag_ids: [42], updated_at: '2026-04-22T10:00:00+00:00' })
    ];
    sessions.applyUpsert(
      sess({ id: 'new-row', tag_ids: [42, 7], updated_at: '2026-04-22T11:00:00+00:00' })
    );
    expect(sessions.list.map((s) => s.id)).toEqual(['new-row', 'existing']);
  });

  it('removes a listed row whose new tag_ids no longer intersect the filter (retag-out)', () => {
    sessions.filter = { tags: [42] };
    sessions.list = [
      sess({ id: 'a', tag_ids: [42] }),
      sess({ id: 'b', tag_ids: [42] })
    ];
    // Row `a` was retagged to {99} on another tab — the upsert frame
    // arrives with the new tag set, and it no longer belongs here.
    sessions.applyUpsert(sess({ id: 'a', tag_ids: [99] }));
    expect(sessions.list.map((s) => s.id)).toEqual(['b']);
  });

  it('clears selectedId when the retagged-out row was the selected row', () => {
    sessions.filter = { tags: [42] };
    sessions.list = [sess({ id: 'a', tag_ids: [42] })];
    sessions.selectedId = 'a';
    sessions.applyUpsert(sess({ id: 'a', tag_ids: [99] }));
    expect(sessions.list).toEqual([]);
    expect(sessions.selectedId).toBeNull();
  });

  it('ignores tag filter when filter.tags is empty array (treated as unfiltered)', () => {
    sessions.filter = { tags: [] };
    sessions.list = [];
    sessions.applyUpsert(sess({ id: 'x', tag_ids: [1] }));
    expect(sessions.list.map((s) => s.id)).toEqual(['x']);
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

  it('clears the persisted composer draft for the deleted session', () => {
    drafts.set('a', 'some draft');
    drafts.flush('a');
    expect(localStorage.getItem('bearings:draft:a')).toBe('some draft');
    sessions.list = [sess({ id: 'a' })];
    sessions.applyDelete('a');
    expect(localStorage.getItem('bearings:draft:a')).toBeNull();
  });
});

describe('draft cleanup hooks', () => {
  it('sessions.remove drops the composer draft for the deleted session', async () => {
    drafts.set('sess-a', 'stale');
    drafts.flush('sess-a');
    expect(localStorage.getItem('bearings:draft:sess-a')).toBe('stale');
    sessions.list = [sess({ id: 'sess-a' })];
    queueResponses([{ ok: true, body: null }]);
    await sessions.remove('sess-a');
    expect(localStorage.getItem('bearings:draft:sess-a')).toBeNull();
  });

  it('sessions.close drops the composer draft (closed sessions are read-only)', async () => {
    drafts.set('sess-a', 'half thought');
    drafts.flush('sess-a');
    expect(localStorage.getItem('bearings:draft:sess-a')).toBe('half thought');
    sessions.list = [sess({ id: 'sess-a', closed_at: null })];
    queueResponses([
      {
        ok: true,
        body: { ...sess({ id: 'sess-a' }), closed_at: '2026-04-22T00:00:00+00:00' }
      },
      // The store also calls tags.refresh() as a side effect — swallow it.
      { ok: true, body: [] }
    ]);
    await sessions.close('sess-a');
    expect(localStorage.getItem('bearings:draft:sess-a')).toBeNull();
  });
});

describe('sessions.applyRunnerState', () => {
  it('adds an id to the running set when is_running is true', () => {
    sessions.running = new Set();
    sessions.applyRunnerState('a', true);
    expect(sessions.running.has('a')).toBe(true);
  });

  it('populates the awaiting set when is_awaiting_user is true', () => {
    sessions.running = new Set();
    sessions.awaiting = new Set();
    sessions.applyRunnerState('a', true, true);
    expect(sessions.running.has('a')).toBe(true);
    expect(sessions.awaiting.has('a')).toBe(true);
  });

  it('clears awaiting when a later frame reports the decision resolved', () => {
    sessions.running = new Set();
    sessions.awaiting = new Set(['a']);
    sessions.applyRunnerState('a', true, false);
    expect(sessions.awaiting.has('a')).toBe(false);
    expect(sessions.running.has('a')).toBe(true);
  });

  it('defaults awaiting to false when the field is omitted (pre-0.10 frame)', () => {
    sessions.running = new Set();
    sessions.awaiting = new Set(['a']);
    sessions.applyRunnerState('a', true);
    expect(sessions.awaiting.has('a')).toBe(false);
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

describe('sessions.startRunningPoll catch behavior', () => {
  it('preserves the previous running Set when listRunningSessions fails', async () => {
    // Seed a non-empty set — represents the prior successful poll.
    sessions.running = new Set(['sess-live']);

    // Next fetch throws. `softRefresh` also runs inside the tick, so
    // it has to see a fetch failure too — queue one rejecting response
    // and enable the passthrough fallback for everything else.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('transport blip');
      })
    );

    sessions.startRunningPoll();
    // startRunningPoll fires its tick synchronously and schedules the
    // interval. Await the microtask queue so the catch branch runs.
    await new Promise((r) => setTimeout(r, 0));
    sessions.stopRunningPoll();

    expect(sessions.running.has('sess-live')).toBe(true);
    expect(sessions.running.size).toBe(1);
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('sessions.running poll failed'),
      expect.any(Error)
    );
  });
});

