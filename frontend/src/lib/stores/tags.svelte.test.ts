import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Tag } from '$lib/api';
import { tags } from './tags.svelte';

afterEach(() => {
  vi.restoreAllMocks();
  tags.list = [];
  tags.error = null;
  tags.loading = false;
});

type Fake = { ok: boolean; status?: number; body: unknown };

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'infra',
    color: null,
    pinned: false,
    sort_order: 0,
    created_at: '2026-04-19T00:00:00+00:00',
    session_count: 0,
    ...overrides
  };
}

/** Install a fetch stub that answers each request from a queue. The
 * queue is indexed by call-order, so each test describes the exact
 * response sequence it expects. */
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

describe('tags store', () => {
  it('refresh populates list on success', async () => {
    queueResponses([{ ok: true, body: [tag({ id: 1, name: 'infra', pinned: true })] }]);
    await tags.refresh();
    expect(tags.error).toBeNull();
    expect(tags.list).toHaveLength(1);
    expect(tags.list[0].pinned).toBe(true);
  });

  it('refresh records error text on failure', async () => {
    queueResponses([{ ok: false, status: 500, body: 'boom' }]);
    await tags.refresh();
    expect(tags.error).toContain('500');
    expect(tags.list).toEqual([]);
  });

  it('create POSTs then re-fetches the list', async () => {
    const created = tag({ id: 2, name: 'bug-repro' });
    queueResponses([
      { ok: true, body: created }, // POST /api/tags
      { ok: true, body: [created] } // GET /api/tags refresh
    ]);
    const result = await tags.create({ name: 'bug-repro' });
    expect(result?.id).toBe(2);
    expect(tags.list).toEqual([created]);
  });

  it('create surfaces a 409 as error', async () => {
    queueResponses([{ ok: false, status: 409, body: 'duplicate' }]);
    const result = await tags.create({ name: 'infra' });
    expect(result).toBeNull();
    expect(tags.error).toContain('409');
  });

  it('remove deletes the row locally on success', async () => {
    tags.list = [tag({ id: 1 }), tag({ id: 2, name: 'other' })];
    queueResponses([{ ok: true, status: 204, body: '' }]);
    const ok = await tags.remove(1);
    expect(ok).toBe(true);
    expect(tags.list.map((t) => t.id)).toEqual([2]);
  });

  it('remove returns false and preserves list on failure', async () => {
    tags.list = [tag({ id: 1 })];
    queueResponses([{ ok: false, status: 404, body: 'not found' }]);
    const ok = await tags.remove(1);
    expect(ok).toBe(false);
    expect(tags.list).toHaveLength(1);
  });

  it('bumpCount clamps at zero', () => {
    tags.list = [tag({ id: 1, session_count: 0 })];
    tags.bumpCount(1, -1);
    expect(tags.list[0].session_count).toBe(0);
    tags.bumpCount(1, +2);
    expect(tags.list[0].session_count).toBe(2);
  });
});
