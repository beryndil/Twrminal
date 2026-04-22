/**
 * SessionList split — v0.3.25 ships the open/closed bucket layout:
 * open sessions render in the main `<ul>`, closed sessions get pushed
 * into a collapsible "Closed (N)" group at the bottom. The group
 * starts collapsed each page load so the sidebar is quiet on boot.
 *
 * These tests drive the rendering by seeding `sessions.list` directly
 * and mock out any API calls SessionList might fire as a side effect.
 */

import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session } from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';
import { tags } from '$lib/stores/tags.svelte';
import SessionList from './SessionList.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
  sessions.loading = false;
  sessions.error = null;
  tags.list = [];
  tags.selected = [];
});

beforeEach(() => {
  // Any side-effectful fetch (tag refresh via TagFilterPanel effects,
  // running-session poll, etc.) resolves to an empty array so nothing
  // blows up during render.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      async json() {
        return [];
      },
      async text() {
        return '[]';
      }
    }))
  );
  // SessionList mounts an $effect that calls sessions.refresh() on
  // first flush (see the filter-key effect at the top of the file).
  // Stub it so the async refresh doesn't overwrite the seeded list
  // between setup and assertions.
  vi.spyOn(sessions, 'refresh').mockResolvedValue(undefined);
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
    ...overrides
  };
}

describe('SessionList open/closed split', () => {
  it('renders open sessions in the main list and hides closed ones by default', () => {
    sessions.list = [
      sess({ id: 'open-1', title: 'Live work', closed_at: null }),
      sess({
        id: 'done-1',
        title: 'Shipped v0.3.24',
        closed_at: '2026-04-20T00:00:00+00:00'
      })
    ];
    const { queryByText, getByTestId } = render(SessionList);
    // Open session is visible.
    expect(queryByText('Live work')).toBeInTheDocument();
    // Closed group is present (with count) but collapsed — the UL isn't rendered.
    expect(getByTestId('closed-group-toggle').textContent).toContain('Closed (1)');
    expect(() => getByTestId('closed-sessions-list')).toThrow();
    // And the closed row's title stays hidden while collapsed.
    expect(queryByText('Shipped v0.3.24')).toBeNull();
  });

  it('toggling "Closed (N)" reveals the closed list', async () => {
    sessions.list = [
      sess({ id: 'open-1', title: 'Live work', closed_at: null }),
      sess({
        id: 'done-1',
        title: 'Shipped v0.3.24',
        closed_at: '2026-04-20T00:00:00+00:00'
      })
    ];
    const { getByText, getByTestId } = render(SessionList);
    const toggle = getByTestId('closed-group-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    // Closed row's title is now visible, rendered inside the revealed UL.
    expect(getByTestId('closed-sessions-list')).toBeInTheDocument();
    expect(getByText('Shipped v0.3.24')).toBeInTheDocument();
  });

  it('suppresses the "Closed" group entirely when no session is closed', () => {
    sessions.list = [sess({ id: 'open-1', title: 'Live work', closed_at: null })];
    const { queryByTestId } = render(SessionList);
    expect(queryByTestId('closed-group-toggle')).toBeNull();
  });

  it('shows the "No open sessions" placeholder when every session is closed', () => {
    sessions.list = [
      sess({
        id: 'done-1',
        title: 'Shipped feature',
        closed_at: '2026-04-20T00:00:00+00:00'
      })
    ];
    const { getByText, getByTestId } = render(SessionList);
    expect(getByText('No open sessions.')).toBeInTheDocument();
    expect(getByTestId('closed-group-toggle').textContent).toContain('Closed (1)');
  });

  it('"Closed (N)" count reflects the store, not the visible list', () => {
    sessions.list = [
      sess({ id: 'a', closed_at: '2026-04-20T00:00:00+00:00' }),
      sess({ id: 'b', closed_at: '2026-04-19T00:00:00+00:00' }),
      sess({ id: 'c', closed_at: '2026-04-18T00:00:00+00:00' }),
      sess({ id: 'd', closed_at: null, title: 'Alive' })
    ];
    const { getByTestId } = render(SessionList);
    expect(getByTestId('closed-group-toggle').textContent).toContain('Closed (3)');
  });
});
