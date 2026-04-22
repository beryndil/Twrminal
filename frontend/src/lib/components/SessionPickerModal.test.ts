import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Session, Tag } from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';
import { tags } from '$lib/stores/tags.svelte';
import SessionPickerModal from './SessionPickerModal.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
  tags.list = [];
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

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'bearings',
    color: null,
    pinned: false,
    sort_order: 0,
    created_at: '2026-04-01T00:00:00+00:00',
    session_count: 1,
    open_session_count: 1,
    default_working_dir: null,
    default_model: null,
    ...overrides
  };
}

beforeEach(() => {
  sessions.list = [
    sess({ id: 'sess-a', title: 'Alpha' }),
    sess({ id: 'sess-b', title: 'Beta', working_dir: '/tmp/b' }),
    sess({ id: 'sess-c', title: 'Gamma', model: 'claude-haiku' })
  ];
  tags.list = [tag({ id: 1, name: 'ship' }), tag({ id: 2, name: 'archive' })];
});

describe('SessionPickerModal', () => {
  it('lists candidate sessions and excludes the source', () => {
    const onPickExisting = vi.fn();
    const { getAllByTestId, queryByText } = render(SessionPickerModal, {
      open: true,
      excludeIds: ['sess-a'],
      onPickExisting,
      onCancel: () => {}
    });
    const rows = getAllByTestId('picker-row');
    expect(rows.map((r) => r.dataset.sessionId)).toEqual(['sess-b', 'sess-c']);
    expect(queryByText('Alpha')).toBeNull();
  });

  it('narrows candidates as the user types', async () => {
    const { getByTestId, getAllByTestId } = render(SessionPickerModal, {
      open: true,
      onPickExisting: () => {},
      onCancel: () => {}
    });
    const search = getByTestId('picker-search') as HTMLInputElement;
    await fireEvent.input(search, { target: { value: 'beta' } });
    const rows = getAllByTestId('picker-row');
    expect(rows.map((r) => r.dataset.sessionId)).toEqual(['sess-b']);
  });

  it('clicking a row fires onPickExisting with that session id', async () => {
    const onPickExisting = vi.fn();
    const { getAllByTestId } = render(SessionPickerModal, {
      open: true,
      excludeIds: ['sess-a'],
      onPickExisting,
      onCancel: () => {}
    });
    await fireEvent.click(getAllByTestId('picker-row')[0]);
    expect(onPickExisting).toHaveBeenCalledWith('sess-b');
  });

  it('Escape cancels', async () => {
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionPickerModal, {
      open: true,
      onPickExisting: () => {},
      onCancel
    });
    await fireEvent.keyDown(getByTestId('session-picker'), { key: 'Escape' });
    expect(onCancel).toHaveBeenCalled();
  });

  it('inline create requires title and at least one tag', async () => {
    const onPickNew = vi.fn();
    const { getByTestId, getByText } = render(SessionPickerModal, {
      open: true,
      onPickExisting: () => {},
      onPickNew,
      onCancel: () => {}
    });
    await fireEvent.click(getByTestId('picker-create-toggle'));
    // Click confirm with no title — should NOT fire, should show error.
    await fireEvent.click(getByTestId('picker-new-confirm'));
    expect(onPickNew).not.toHaveBeenCalled();
    expect(getByText(/Title required/)).toBeInTheDocument();

    const titleInput = getByTestId('picker-new-title') as HTMLInputElement;
    await fireEvent.input(titleInput, { target: { value: 'Fresh session' } });
    // Still no tag — should fail with a different message.
    await fireEvent.click(getByTestId('picker-new-confirm'));
    expect(onPickNew).not.toHaveBeenCalled();
    expect(getByText(/at least one tag/i)).toBeInTheDocument();
  });

  it('inline create emits onPickNew with the draft once valid', async () => {
    const onPickNew = vi.fn();
    const { getByTestId, getByRole } = render(SessionPickerModal, {
      open: true,
      onPickExisting: () => {},
      onPickNew,
      onCancel: () => {}
    });
    await fireEvent.click(getByTestId('picker-create-toggle'));
    const titleInput = getByTestId('picker-new-title') as HTMLInputElement;
    await fireEvent.input(titleInput, { target: { value: 'Triage spill' } });
    // Tag buttons render as toggle buttons inside the create form.
    // Select the "ship" tag.
    const shipBtn = getByRole('button', { name: /ship/ });
    await fireEvent.click(shipBtn);
    await fireEvent.click(getByTestId('picker-new-confirm'));
    expect(onPickNew).toHaveBeenCalledWith({
      title: 'Triage spill',
      tag_ids: [1]
    });
  });

  it('allowCreate=false hides the create-new affordance', () => {
    const { queryByTestId } = render(SessionPickerModal, {
      open: true,
      allowCreate: false,
      onPickExisting: () => {},
      onCancel: () => {}
    });
    expect(queryByTestId('picker-create-toggle')).toBeNull();
  });
});
