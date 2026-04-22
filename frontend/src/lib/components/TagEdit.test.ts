import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Tag } from '$lib/api';
import { tags } from '$lib/stores/tags.svelte';
import TagEdit from './TagEdit.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'bearings',
    color: null,
    pinned: true,
    sort_order: 0,
    created_at: '2026-04-19T00:00:00+00:00',
    session_count: 3,
    open_session_count: 2,
    default_working_dir: null,
    default_model: null,
    tag_group: 'general',
    ...overrides
  };
}

type Fake = { ok: boolean; status?: number; body: unknown };

function queueResponses(queue: Fake[]): ReturnType<typeof vi.fn> {
  let i = 0;
  const stub = vi.fn(async () => {
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
  });
  vi.stubGlobal('fetch', stub);
  return stub;
}

beforeEach(() => {
  tags.list = [tag()];
  tags.error = null;
});

describe('TagEdit memory editor', () => {
  it('loads existing memory content into the editor', async () => {
    queueResponses([
      {
        ok: true,
        body: { tag_id: 1, content: 'remember nftables', updated_at: 'x' }
      }
    ]);
    const { container } = render(TagEdit, {
      props: { open: true, tagId: 1 }
    });
    await waitFor(() => {
      const ta = container.querySelector('textarea') as HTMLTextAreaElement;
      expect(ta.value).toBe('remember nftables');
    });
  });

  it('treats a 404 from GET /memory as empty', async () => {
    queueResponses([{ ok: false, status: 404, body: { detail: 'tag memory not found' } }]);
    const { container } = render(TagEdit, {
      props: { open: true, tagId: 1 }
    });
    await waitFor(() => {
      const ta = container.querySelector('textarea') as HTMLTextAreaElement;
      // No error badge and the textarea is empty — 404 means "no memory yet".
      expect(ta.value).toBe('');
    });
  });

  it('save path PUTs memory when content is non-empty', async () => {
    const stub = queueResponses([
      {
        ok: true,
        body: { tag_id: 1, content: 'seeded', updated_at: 'x' }
      }, // initial GET /memory — pretend memory already exists
      { ok: true, body: tag({ name: 'bearings' }) }, // PATCH tag
      { ok: true, body: [tag({ name: 'bearings' })] }, // tags.refresh after update
      {
        ok: true,
        body: { tag_id: 1, content: 'seeded', updated_at: 'x' }
      } // PUT /memory
    ]);
    const { container, getByRole } = render(TagEdit, {
      props: { open: true, tagId: 1 }
    });
    // Wait for initial GET /memory to populate the textarea. Using
    // pre-seeded content sidesteps the jsdom Svelte 5 bind:value
    // quirk where a programmatic `fireEvent.input` on a textarea
    // doesn't always propagate back to the bound state.
    await waitFor(() => {
      const el = container.querySelector('textarea') as HTMLTextAreaElement;
      expect(el.value).toBe('seeded');
    });
    await fireEvent.click(getByRole('button', { name: /save/i }));

    await waitFor(() => {
      const calls = stub.mock.calls.map((c) => [c[0], (c[1] as RequestInit)?.method ?? 'GET']);
      expect(calls).toContainEqual(['/api/tags/1/memory', 'PUT']);
    });
  });

  it('clearing an existing memory triggers DELETE', async () => {
    const stub = queueResponses([
      {
        ok: true,
        body: { tag_id: 1, content: 'old memory', updated_at: 'x' }
      }, // GET /memory — exists
      { ok: true, body: tag({ name: 'bearings' }) }, // PATCH tag
      { ok: true, body: [tag({ name: 'bearings' })] }, // tags.refresh
      { ok: true, body: '' } // DELETE /memory
    ]);
    const { container, getByRole } = render(TagEdit, {
      props: { open: true, tagId: 1 }
    });
    const ta = (await waitFor(() => {
      const el = container.querySelector('textarea') as HTMLTextAreaElement;
      if (el.value !== 'old memory') throw new Error('not loaded yet');
      return el;
    })) as HTMLTextAreaElement;
    ta.value = '';
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    await fireEvent.click(getByRole('button', { name: /save/i }));

    await waitFor(() => {
      const calls = stub.mock.calls.map((c) => [c[0], (c[1] as RequestInit)?.method ?? 'GET']);
      expect(calls).toContainEqual(['/api/tags/1/memory', 'DELETE']);
    });
  });

  it('preview toggle renders markdown', async () => {
    queueResponses([
      { ok: true, body: { tag_id: 1, content: '# Heading', updated_at: 'x' } }
    ]);
    const { container, getByRole } = render(TagEdit, {
      props: { open: true, tagId: 1 }
    });
    await waitFor(() => {
      const ta = container.querySelector('textarea') as HTMLTextAreaElement;
      expect(ta.value).toBe('# Heading');
    });
    await fireEvent.click(getByRole('button', { name: /preview/i }));
    await waitFor(() => {
      expect(container.querySelector('h1')?.textContent).toBe('Heading');
    });
  });
});
