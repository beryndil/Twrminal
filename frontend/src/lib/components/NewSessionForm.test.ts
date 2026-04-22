import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Tag } from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';
import { tags } from '$lib/stores/tags.svelte';
import { prefs } from '$lib/stores/prefs.svelte';
import { agent } from '$lib/agent.svelte';
import NewSessionForm from './NewSessionForm.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
  tags.list = [];
  tags.selected = [];
});

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'infra',
    color: null,
    pinned: false,
    sort_order: 0,
    created_at: '2026-04-19T00:00:00+00:00',
    session_count: 0,
    open_session_count: 0,
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
  tags.list = [tag({ id: 1, name: 'infra' })];
  tags.selected = [1];
  prefs.defaultWorkingDir = '/tmp';
  prefs.defaultModel = 'claude-opus-4-7';
});

describe('NewSessionForm kind toggle', () => {
  it('hides Budget and Model inputs when Checklist is selected', async () => {
    const { getByRole, queryByPlaceholderText, queryByText } = render(NewSessionForm, {
      open: true
    });
    // Chat is the default kind — Budget + Model both rendered.
    expect(queryByPlaceholderText('no cap')).not.toBeNull();
    expect(queryByText('Model')).not.toBeNull();

    const checklistBtn = getByRole('radio', { name: /Checklist/ });
    await fireEvent.click(checklistBtn);

    expect(queryByPlaceholderText('no cap')).toBeNull();
    expect(queryByText('Model')).toBeNull();
  });

  it('posts kind=checklist and does NOT open an agent connection on submit', async () => {
    const stub = queueResponses([
      {
        ok: true,
        body: {
          id: 'sess-new',
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
          last_context_max: null,
          closed_at: null,
          kind: 'checklist'
        }
      }
    ]);
    const connectSpy = vi.spyOn(agent, 'connect').mockResolvedValue();

    const { getByRole } = render(NewSessionForm, { open: true });
    await fireEvent.click(getByRole('radio', { name: /Checklist/ }));
    await fireEvent.click(getByRole('button', { name: /Create session/ }));

    await waitFor(() => expect(stub).toHaveBeenCalledTimes(1));
    const [, init] = stub.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.kind).toBe('checklist');
    // Checklist sessions skip the WS connect — the runner rejects them.
    expect(connectSpy).not.toHaveBeenCalled();
  });

  it('chat submission still opens the agent connection', async () => {
    const stub = queueResponses([
      {
        ok: true,
        body: {
          id: 'sess-chat',
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
          last_context_max: null,
          closed_at: null,
          kind: 'chat',
          checklist_item_id: null
        }
      }
    ]);
    const connectSpy = vi.spyOn(agent, 'connect').mockResolvedValue();

    const { getByRole } = render(NewSessionForm, { open: true });
    await fireEvent.click(getByRole('button', { name: /Create session/ }));

    await waitFor(() => expect(stub).toHaveBeenCalledTimes(1));
    const [, init] = stub.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.kind).toBe('chat');
    await waitFor(() => expect(connectSpy).toHaveBeenCalledWith('sess-chat'));
  });
});
