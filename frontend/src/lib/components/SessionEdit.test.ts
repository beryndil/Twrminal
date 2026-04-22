import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session, Tag } from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';
import { tags } from '$lib/stores/tags.svelte';
import SessionEdit from './SessionEdit.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: 'sess-1',
    created_at: '2026-04-19T00:00:00+00:00',
    updated_at: '2026-04-19T00:00:00+00:00',
    working_dir: '/tmp',
    model: 'claude-sonnet-4-6',
    title: 'demo',
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

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'infra',
    color: null,
    pinned: false,
    sort_order: 0,
    created_at: '2026-04-19T00:00:00+00:00',
    session_count: 0,
    default_working_dir: null,
    default_model: null,
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
  sessions.list = [session()];
  tags.list = [tag({ id: 1, name: 'infra' }), tag({ id: 2, name: 'bug-repro' })];
  tags.error = null;
});

describe('SessionEdit tags', () => {
  it('renders attached tags on open and detaches on ✕', async () => {
    queueResponses([
      { ok: true, body: [tag({ id: 1, name: 'infra' })] }, // listSessionTags
      { ok: true, body: [] } // detach → empty list
    ]);
    const { getByLabelText, queryByText } = render(SessionEdit, {
      props: { open: true, sessionId: 'sess-1' }
    });
    await waitFor(() => expect(queryByText('infra')).not.toBeNull());
    await fireEvent.click(getByLabelText('Detach infra'));
    await waitFor(() => expect(queryByText('infra')).toBeNull());
  });

  it('clicking a suggestion attaches an existing tag', async () => {
    queueResponses([
      { ok: true, body: [] }, // listSessionTags (none attached)
      { ok: true, body: [tag({ id: 2, name: 'bug-repro' })] } // attach
    ]);
    const { getByLabelText, getByRole, queryByText } = render(SessionEdit, {
      props: { open: true, sessionId: 'sess-1' }
    });
    // Trigger suggestions by typing in the tag input.
    await fireEvent.input(getByLabelText('Tag name'), { target: { value: 'bug' } });
    await fireEvent.click(getByRole('button', { name: '+ bug-repro' }));
    await waitFor(() => expect(queryByText('bug-repro')).not.toBeNull());
  });

  it('pressing Enter on a novel name creates and attaches a new tag', async () => {
    const created = tag({ id: 3, name: 'new-one' });
    queueResponses([
      { ok: true, body: [] }, // listSessionTags
      { ok: true, body: created }, // createTag
      { ok: true, body: [created] }, // refresh after create
      { ok: true, body: [created] } // attachSessionTag
    ]);
    const { getByLabelText, queryByText } = render(SessionEdit, {
      props: { open: true, sessionId: 'sess-1' }
    });
    const input = getByLabelText('Tag name') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'new-one' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(queryByText('new-one')).not.toBeNull());
  });
});
