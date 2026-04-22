import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session } from '$lib/api';
import { checklists } from '$lib/stores/checklists.svelte';
import { sessions } from '$lib/stores/sessions.svelte';
import ChecklistView from './ChecklistView.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
  checklists.reset();
});

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: 'sess-cl',
    created_at: '2026-04-21T00:00:00+00:00',
    updated_at: '2026-04-21T00:00:00+00:00',
    working_dir: '/tmp',
    model: 'claude-opus-4-7',
    title: 'Grocery run',
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
    kind: 'checklist',
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

const EMPTY_CHECKLIST = {
  session_id: 'sess-cl',
  notes: null,
  created_at: '2026-04-21T00:00:00+00:00',
  updated_at: '2026-04-21T00:00:00+00:00',
  items: []
};

beforeEach(() => {
  sessions.list = [session()];
  sessions.selectedId = 'sess-cl';
});

describe('ChecklistView', () => {
  it('loads the checklist for the selected session and renders the add-item form', async () => {
    queueResponses([{ ok: true, body: EMPTY_CHECKLIST }]);
    render(ChecklistView);
    await waitFor(() => expect(checklists.current?.session_id).toBe('sess-cl'));
    // Add-item input rendered, Add button disabled while empty.
    await waitFor(() => {
      const btn = document.querySelector(
        'button[type="submit"]'
      ) as HTMLButtonElement | null;
      expect(btn).not.toBeNull();
      expect(btn!.disabled).toBe(true);
    });
  });

  it('optimistically renders a new item after Add', async () => {
    queueResponses([
      { ok: true, body: EMPTY_CHECKLIST },
      {
        ok: true,
        body: {
          id: 42,
          checklist_id: 'sess-cl',
          parent_item_id: null,
          label: 'Pick up milk',
          notes: null,
          checked_at: null,
          sort_order: 0,
          created_at: '2026-04-21T00:01:00+00:00',
          updated_at: '2026-04-21T00:01:00+00:00'
        }
      }
    ]);
    const { getByPlaceholderText, findByText } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());

    const input = getByPlaceholderText('Add item…') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'Pick up milk' } });
    await fireEvent.submit(input.closest('form')!);

    // Optimistic entry appears before the POST resolves; the
    // server-confirmed row arrives on the subsequent tick.
    await findByText('Pick up milk');
  });

  it('rolls back an optimistic add when the POST fails', async () => {
    queueResponses([
      { ok: true, body: EMPTY_CHECKLIST },
      { ok: false, status: 500, body: 'boom' }
    ]);
    const { getByPlaceholderText, queryByText } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());

    const input = getByPlaceholderText('Add item…') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'Ghost item' } });
    await fireEvent.submit(input.closest('form')!);

    // After the failure lands the store restores the previous
    // (empty) list, so the ghost label must disappear.
    await waitFor(() => expect(queryByText('Ghost item')).toBeNull());
    expect(checklists.error).not.toBeNull();
  });
});
