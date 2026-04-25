import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session } from '$lib/api';
import { agent } from '$lib/agent.svelte';
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
  // v0.5.2: ChecklistView embeds ChecklistChat, which calls
  // `agent.connect(sid)` on mount. `connect` internally fetches the
  // session row via `conversation.load` — left unmocked, it pulls from
  // the per-test `queueResponses` queue and fails with "unexpected
  // fetch call". Stub it by default; tests that need to observe the
  // call (paired-chat spawn, paired-chat link click) still re-spy and
  // assert on that spy.
  vi.spyOn(agent, 'connect').mockResolvedValue();
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

// ---------------------------------------------------------------------------
// Slice 4: per-item paired-chat affordance
// ---------------------------------------------------------------------------

const CHECKLIST_WITH_ONE_ITEM = {
  session_id: 'sess-cl',
  notes: null,
  created_at: '2026-04-21T00:00:00+00:00',
  updated_at: '2026-04-21T00:00:00+00:00',
  items: [
    {
      id: 7,
      checklist_id: 'sess-cl',
      parent_item_id: null,
      label: 'Install deps',
      notes: null,
      checked_at: null,
      sort_order: 0,
      created_at: '2026-04-21T00:00:00+00:00',
      updated_at: '2026-04-21T00:00:00+00:00',
      chat_session_id: null
    }
  ]
};

const PAIRED_CHAT_SESSION: Session = {
  id: 'chat-1',
  created_at: '2026-04-21T00:01:00+00:00',
  updated_at: '2026-04-21T00:01:00+00:00',
  working_dir: '/tmp',
  model: 'claude-opus-4-7',
  title: 'Install deps',
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
  checklist_item_id: 7,
  last_completed_at: null,
  last_viewed_at: null,
  tag_ids: [],
  pinned: false,
  error_pending: false
};

describe('ChecklistView paired-chat affordance', () => {
  it('clicking "Work on this" spawns a paired chat and selects it', async () => {
    queueResponses([
      { ok: true, body: CHECKLIST_WITH_ONE_ITEM },
      { ok: true, body: PAIRED_CHAT_SESSION }
    ]);
    const connectSpy = vi.spyOn(agent, 'connect').mockResolvedValue();
    const { getByRole } = render(ChecklistView);
    await waitFor(() => expect(checklists.current?.items.length).toBe(1));
    const btn = getByRole('button', { name: /Work on Install deps/ });
    await fireEvent.click(btn);
    await waitFor(() => expect(sessions.selectedId).toBe('chat-1'));
    // The newly-spawned chat must be in the sidebar list and the
    // agent runner must have been asked to connect. (The checklist
    // store itself is reset right after select() because the effect
    // detects `kind === 'chat'` — so the pairing pointer survives
    // in the sidebar's session row, not the checklist store.)
    expect(sessions.list.some((s) => s.id === 'chat-1')).toBe(true);
    expect(connectSpy).toHaveBeenCalledWith('chat-1');
  });

  it('renders paired-chat link affordance once the item is paired', async () => {
    const paired = {
      ...CHECKLIST_WITH_ONE_ITEM,
      items: [
        {
          ...CHECKLIST_WITH_ONE_ITEM.items[0],
          chat_session_id: 'chat-1'
        }
      ]
    };
    queueResponses([{ ok: true, body: paired }]);
    // The paired session has to exist in the sidebar list for the
    // title-link to render.
    sessions.list = [session(), PAIRED_CHAT_SESSION];
    const { getByRole, queryByRole } = render(ChecklistView);
    await waitFor(() => expect(checklists.current?.items.length).toBe(1));
    // The paired-chat title link replaces the old "Continue working"
    // hover affordance — always-visible, aria-label is "Open paired
    // chat: <title>". The "Work on" spawn button disappears on a
    // paired item.
    expect(getByRole('button', { name: /Open paired chat: Install deps/ })).toBeTruthy();
    expect(queryByRole('button', { name: /Work on Install deps/ })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Slice 4.1: tightened paired-chat coupling + nested rendering
// ---------------------------------------------------------------------------

const CHECKLIST_WITH_PAIRED_ITEM = {
  session_id: 'sess-cl',
  notes: null,
  created_at: '2026-04-21T00:00:00+00:00',
  updated_at: '2026-04-21T00:00:00+00:00',
  items: [
    {
      id: 7,
      checklist_id: 'sess-cl',
      parent_item_id: null,
      label: 'Install deps',
      notes: null,
      checked_at: null,
      sort_order: 0,
      created_at: '2026-04-21T00:00:00+00:00',
      updated_at: '2026-04-21T00:00:00+00:00',
      chat_session_id: 'chat-1'
    }
  ]
};

const CHECKLIST_WITH_NESTED = {
  session_id: 'sess-cl',
  notes: null,
  created_at: '2026-04-21T00:00:00+00:00',
  updated_at: '2026-04-21T00:00:00+00:00',
  items: [
    {
      id: 1,
      checklist_id: 'sess-cl',
      parent_item_id: null,
      label: 'Root parent',
      notes: null,
      checked_at: null,
      sort_order: 0,
      created_at: '2026-04-21T00:00:00+00:00',
      updated_at: '2026-04-21T00:00:00+00:00',
      chat_session_id: null
    },
    {
      id: 2,
      checklist_id: 'sess-cl',
      parent_item_id: 1,
      label: 'Child leaf',
      notes: null,
      checked_at: null,
      sort_order: 0,
      created_at: '2026-04-21T00:00:00+00:00',
      updated_at: '2026-04-21T00:00:00+00:00',
      chat_session_id: null
    }
  ]
};

describe('ChecklistView Slice 4.1', () => {
  it('checking a paired item closes the chat without a confirm', async () => {
    // Toggle path: PATCH item (returns updated) → GET /checklist (store
    // re-fetch after cascade) → close_session (sessions.close) →
    // sessions.refresh (GET /sessions) from handleToggle's post-check.
    const toggledItem = {
      ...CHECKLIST_WITH_PAIRED_ITEM.items[0],
      checked_at: '2026-04-21T00:02:00+00:00'
    };
    const toggledChecklist = { ...CHECKLIST_WITH_PAIRED_ITEM, items: [toggledItem] };
    const closedChat = { ...PAIRED_CHAT_SESSION, closed_at: '2026-04-21T00:02:00+00:00' };
    queueResponses([
      { ok: true, body: CHECKLIST_WITH_PAIRED_ITEM }, // initial load
      { ok: true, body: closedChat }, // sessions.close
      { ok: true, body: toggledItem }, // PATCH toggle
      { ok: true, body: toggledChecklist }, // re-fetch after cascade
      { ok: true, body: [closedChat] } // sessions.refresh after check
    ]);
    // Seed the paired chat session into the sidebar so handleToggle
    // can find it and call sessions.close.
    sessions.list = [session(), PAIRED_CHAT_SESSION];
    const confirmSpy = vi.spyOn(window, 'confirm');
    const { container } = render(ChecklistView);
    await waitFor(() => expect(checklists.current?.items.length).toBe(1));
    // Scope the selector to the item LI — the header now also carries
    // a tour-mode checkbox, so a bare `input[type="checkbox"]` would
    // grab that one instead of the item's.
    const box = container.querySelector(
      'li[data-item-id] input[type="checkbox"]'
    ) as HTMLInputElement | null;
    expect(box).not.toBeNull();
    await fireEvent.click(box!);
    // No confirm dialog — the click flow must never prompt.
    await waitFor(() => expect(checklists.current?.items[0].checked_at).not.toBeNull());
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('renders the paired chat title as a sky-colored link next to the item', async () => {
    queueResponses([{ ok: true, body: CHECKLIST_WITH_PAIRED_ITEM }]);
    // The paired chat must be visible in sessions.list for the link to
    // resolve — the ChecklistView looks it up by id to render the title.
    sessions.list = [session(), PAIRED_CHAT_SESSION];
    const { container } = render(ChecklistView);
    await waitFor(() => expect(checklists.current?.items.length).toBe(1));
    const link = container.querySelector(
      '[data-testid="paired-chat-link"]'
    ) as HTMLButtonElement | null;
    expect(link).not.toBeNull();
    expect(link!.textContent).toMatch(/Install deps/);
    // Class carries the sky-400 color so it's never an ignore-me glyph.
    expect(link!.className).toMatch(/text-sky-400/);
  });

  it('clicking the paired-chat link selects that session', async () => {
    queueResponses([{ ok: true, body: CHECKLIST_WITH_PAIRED_ITEM }]);
    sessions.list = [session(), PAIRED_CHAT_SESSION];
    const connectSpy = vi.spyOn(agent, 'connect').mockResolvedValue();
    const { container } = render(ChecklistView);
    await waitFor(() => expect(checklists.current?.items.length).toBe(1));
    const link = container.querySelector(
      '[data-testid="paired-chat-link"]'
    ) as HTMLButtonElement;
    await fireEvent.click(link);
    await waitFor(() => expect(sessions.selectedId).toBe('chat-1'));
    expect(connectSpy).toHaveBeenCalledWith('chat-1');
  });

  // --- autonomous-run UI ------------------------------------------
  //
  // Backed by `POST/GET/DELETE /api/sessions/{id}/checklist/run`.
  // The ChecklistView header gains a "Run autonomously" button that
  // flips to "Stop" while a driver is active, with a status pill
  // that surfaces counters + outcome. Tests drive via the button
  // clicks; polling-loop timing is covered by the Python driver
  // tests, not re-proven here.

  it('shows "Run autonomously" button when checklist is loaded and open', async () => {
    queueResponses([{ ok: true, body: EMPTY_CHECKLIST }]);
    const { queryByTestId } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());
    await waitFor(() => {
      expect(queryByTestId('auto-run-start')).not.toBeNull();
    });
    expect(queryByTestId('auto-run-stop')).toBeNull();
    expect(queryByTestId('auto-run-pill')).toBeNull();
  });

  it('hides Run button when the checklist session is closed', async () => {
    queueResponses([{ ok: true, body: EMPTY_CHECKLIST }]);
    sessions.list = [session({ closed_at: '2026-04-21T00:10:00+00:00' })];
    const { queryByTestId } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());
    // Give the $effect a tick to settle.
    await new Promise((r) => setTimeout(r, 20));
    expect(queryByTestId('auto-run-start')).toBeNull();
  });

  it('Tour-mode checkbox sends failure_policy=skip + visit_existing on POST /run', async () => {
    // Captures the actual POST body so the assertion can prove the
    // tour-mode payload reaches the wire — the regression in the
    // 2026-04-24 fae8f1a8 run was that the UI couldn't even SEND
    // these fields, so the run silently used halt-mode defaults.
    const stub = queueResponses([
      { ok: true, body: EMPTY_CHECKLIST },
      {
        ok: true,
        status: 202,
        body: {
          state: 'running',
          items_completed: 0,
          items_failed: 0,
          legs_spawned: 0
        }
      }
    ]);
    const { getByTestId } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());
    const tourBox = getByTestId('auto-run-tour-mode') as HTMLInputElement;
    expect(tourBox.checked).toBe(false);
    await fireEvent.click(tourBox);
    expect(tourBox.checked).toBe(true);
    await fireEvent.click(getByTestId('auto-run-start'));
    await waitFor(() => expect(stub).toHaveBeenCalledTimes(2));
    // Second call is POST /run; first is the initial checklist load.
    const postCall = stub.mock.calls[1];
    const init = postCall[1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body.failure_policy).toBe('skip');
    expect(body.visit_existing_sessions).toBe(true);
  });

  it('Tour-mode off sends an empty body so the server uses defaults', async () => {
    // Negative case: the absence of tour-mode means the body is `{}`
    // and the server falls through to halt-mode + spawn-fresh defaults.
    // Confirms the tourMode toggle is the ONLY thing flipping the
    // payload — no leakage from prior runs or unrelated state.
    const stub = queueResponses([
      { ok: true, body: EMPTY_CHECKLIST },
      {
        ok: true,
        status: 202,
        body: {
          state: 'running',
          items_completed: 0,
          items_failed: 0,
          legs_spawned: 0
        }
      }
    ]);
    const { getByTestId } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());
    await fireEvent.click(getByTestId('auto-run-start'));
    await waitFor(() => expect(stub).toHaveBeenCalledTimes(2));
    const init = stub.mock.calls[1][1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({});
  });

  it('clicking Run autonomously POSTs /run and shows a running pill + Stop button', async () => {
    queueResponses([
      { ok: true, body: EMPTY_CHECKLIST },
      {
        ok: true,
        status: 202,
        body: {
          state: 'running',
          items_completed: 0,
          items_failed: 0,
          legs_spawned: 1
        }
      }
    ]);
    const { getByTestId, queryByTestId } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());
    const runBtn = getByTestId('auto-run-start');
    await fireEvent.click(runBtn);
    await waitFor(() => {
      expect(queryByTestId('auto-run-pill')).not.toBeNull();
    });
    const pill = getByTestId('auto-run-pill');
    expect(pill.textContent).toMatch(/running/);
    expect(queryByTestId('auto-run-stop')).not.toBeNull();
    // The idle button is now gone — Stop has replaced it.
    expect(queryByTestId('auto-run-start')).toBeNull();
  });

  it('clicking Stop DELETEs /run and clears the pill', async () => {
    queueResponses([
      { ok: true, body: EMPTY_CHECKLIST },
      {
        ok: true,
        status: 202,
        body: { state: 'running', items_completed: 0, items_failed: 0, legs_spawned: 1 }
      },
      // DELETE → 204 (voidFetch tolerates empty body).
      { ok: true, status: 204, body: '' },
      // After stop, ChecklistView reloads the checklist.
      { ok: true, body: EMPTY_CHECKLIST }
    ]);
    const { getByTestId, queryByTestId } = render(ChecklistView);
    await waitFor(() => expect(checklists.current).not.toBeNull());
    await fireEvent.click(getByTestId('auto-run-start'));
    await waitFor(() => expect(queryByTestId('auto-run-stop')).not.toBeNull());
    await fireEvent.click(getByTestId('auto-run-stop'));
    await waitFor(() => {
      expect(queryByTestId('auto-run-pill')).toBeNull();
      expect(queryByTestId('auto-run-start')).not.toBeNull();
    });
  });

  it('renders parents with a disabled checkbox and nested children', async () => {
    queueResponses([{ ok: true, body: CHECKLIST_WITH_NESTED }]);
    const { container } = render(ChecklistView);
    await waitFor(() => expect(checklists.current?.items.length).toBe(2));
    const parentLi = container.querySelector('li[data-item-id="1"]');
    expect(parentLi).not.toBeNull();
    expect(parentLi!.getAttribute('data-parent')).toBe('true');
    const parentBox = parentLi!.querySelector(
      'input[type="checkbox"]'
    ) as HTMLInputElement;
    expect(parentBox.disabled).toBe(true);
    // Child rendered inside the parent's subtree, not at the root level.
    const childLi = parentLi!.querySelector('li[data-item-id="2"]');
    expect(childLi).not.toBeNull();
    const childBox = childLi!.querySelector(
      'input[type="checkbox"]'
    ) as HTMLInputElement;
    expect(childBox.disabled).toBe(false);
  });
});
