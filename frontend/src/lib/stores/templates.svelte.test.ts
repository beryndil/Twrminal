import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Session, Template } from '$lib/api';
import { sessions } from './sessions.svelte';
import { templates } from './templates.svelte';

afterEach(() => {
  vi.restoreAllMocks();
  templates._reset();
  sessions.list = [];
  sessions.selectedId = null;
});

type Fake = { ok: boolean; status?: number; body: unknown };

function tpl(overrides: Partial<Template> = {}): Template {
  return {
    id: 't-1',
    name: 'template',
    body: null,
    working_dir: null,
    model: null,
    session_instructions: null,
    tag_ids: [],
    created_at: '2026-04-22T00:00:00Z',
    ...overrides
  };
}

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: 's-new',
    working_dir: '/tmp',
    model: 'claude-sonnet-4-6',
    title: 'from template',
    created_at: '2026-04-22T00:00:00Z',
    updated_at: '2026-04-22T00:00:00Z',
    closed_at: null,
    last_viewed_at: null,
    last_completed_at: null,
    message_count: 0,
    total_cost_usd: 0,
    pinned: false,
    tag_ids: [],
    checklist_item_id: null,
    ...overrides
  } as Session;
}

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

describe('templates store', () => {
  it('refresh populates the list from GET /api/templates', async () => {
    queueResponses([
      { ok: true, body: [tpl({ id: 't-1', name: 'alpha' }), tpl({ id: 't-2', name: 'beta' })] }
    ]);
    await templates.refresh();
    expect(templates.list).toHaveLength(2);
    expect(templates.list[0].name).toBe('alpha');
  });

  it('refresh surfaces server errors without clobbering the prior list', async () => {
    queueResponses([
      { ok: true, body: [tpl({ id: 't-1' })] },
      { ok: false, status: 500, body: 'boom' }
    ]);
    await templates.refresh();
    await templates.refresh();
    expect(templates.error).not.toBeNull();
    // Prior list stays — a failed refresh shouldn't wipe the picker.
    expect(templates.list).toHaveLength(1);
  });

  it('create prepends the new template', async () => {
    queueResponses([
      { ok: true, body: [tpl({ id: 't-old' })] },
      { ok: true, body: tpl({ id: 't-new', name: 'fresh' }) }
    ]);
    await templates.refresh();
    const created = await templates.create({ name: 'fresh' });
    expect(created?.id).toBe('t-new');
    expect(templates.list.map((t) => t.id)).toEqual(['t-new', 't-old']);
  });

  it('remove is optimistic and restores on server failure', async () => {
    queueResponses([
      { ok: true, body: [tpl({ id: 't-1' })] },
      { ok: false, status: 500, body: 'boom' }
    ]);
    await templates.refresh();
    const removed = await templates.remove('t-1');
    expect(removed).toBe(false);
    expect(templates.list.map((t) => t.id)).toEqual(['t-1']);
  });

  it('remove drops the row on a 204', async () => {
    queueResponses([
      { ok: true, body: [tpl({ id: 't-1' }), tpl({ id: 't-2' })] },
      { ok: true, status: 204, body: null }
    ]);
    await templates.refresh();
    const removed = await templates.remove('t-1');
    expect(removed).toBe(true);
    expect(templates.list.map((t) => t.id)).toEqual(['t-2']);
  });

  it('remove returns false for unknown id without hitting the server', async () => {
    queueResponses([]);
    const removed = await templates.remove('never-loaded');
    expect(removed).toBe(false);
  });

  it('instantiate upserts the new session into the sessions store', async () => {
    queueResponses([
      { ok: true, body: session({ id: 's-from-tpl' }) }
    ]);
    const created = await templates.instantiate('t-1', { title: 'go' });
    expect(created?.id).toBe('s-from-tpl');
    expect(sessions.list.some((s) => s.id === 's-from-tpl')).toBe(true);
  });

  it('instantiate surfaces server errors as null return', async () => {
    queueResponses([{ ok: false, status: 400, body: 'missing working_dir' }]);
    const created = await templates.instantiate('t-1', {});
    expect(created).toBeNull();
    expect(templates.error).not.toBeNull();
  });
});
