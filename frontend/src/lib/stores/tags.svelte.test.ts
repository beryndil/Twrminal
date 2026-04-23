import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Tag } from '$lib/api';
import { tags, SEVERITY_NONE_ID } from './tags.svelte';

afterEach(() => {
  vi.restoreAllMocks();
  tags.list = [];
  tags.error = null;
  tags.loading = false;
  tags.selected = [];
  tags.selectedSeverity = [];
  tags.panelCollapsed = false;
  // Clear the persisted panel collapse key so tests stay independent.
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.removeItem('bearings.tagFilterPanel.collapsed');
    } catch {
      // ignore
    }
  }
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
    open_session_count: 0,
    default_working_dir: null,
    default_model: null,
    tag_group: 'general',
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
    tags.list = [tag({ id: 1, session_count: 0, open_session_count: 0 })];
    tags.bumpCount(1, -1);
    expect(tags.list[0].session_count).toBe(0);
    expect(tags.list[0].open_session_count).toBe(0);
    tags.bumpCount(1, +2);
    expect(tags.list[0].session_count).toBe(2);
    expect(tags.list[0].open_session_count).toBe(2);
  });

  it('bumpCount defaults openDelta to delta when omitted', () => {
    tags.list = [tag({ id: 1, session_count: 5, open_session_count: 3 })];
    tags.bumpCount(1, +1);
    expect(tags.list[0].session_count).toBe(6);
    expect(tags.list[0].open_session_count).toBe(4);
  });

  it('bumpCount respects explicit openDelta of 0 (closed-session attach)', () => {
    tags.list = [tag({ id: 1, session_count: 5, open_session_count: 3 })];
    tags.bumpCount(1, +1, 0);
    expect(tags.list[0].session_count).toBe(6);
    expect(tags.list[0].open_session_count).toBe(3);
  });

  it('selectGeneral (plain click) single-selects, and toggles off on solo re-click', () => {
    // Plain click from empty → sole selection.
    tags.selectGeneral(1);
    expect(tags.selected).toEqual([1]);
    expect(tags.hasFilter).toBe(true);
    // Plain click on a different tag while one is already selected
    // replaces the selection — no multi-select without the modifier.
    tags.selectGeneral(2);
    expect(tags.selected).toEqual([2]);
    // Plain click on the currently-sole selection clears it.
    tags.selectGeneral(2);
    expect(tags.selected).toEqual([]);
    expect(tags.hasFilter).toBe(false);
  });

  it('selectGeneral with additive=true toggles within the current selection', () => {
    tags.selectGeneral(1);
    tags.selectGeneral(2, { additive: true });
    expect(tags.selected).toEqual([1, 2]);
    // Shift-click on an already-selected id removes it.
    tags.selectGeneral(1, { additive: true });
    expect(tags.selected).toEqual([2]);
    // Shift-click on a fresh id adds it.
    tags.selectGeneral(3, { additive: true });
    expect(tags.selected).toEqual([2, 3]);
  });

  it('plain click on a non-solo member of a multi-selection collapses to just that id', () => {
    // Build a two-id selection via shift-click, then a plain click on
    // one of them should reset to that one only (Finder semantics).
    tags.selectGeneral(1);
    tags.selectGeneral(2, { additive: true });
    expect(tags.selected).toEqual([1, 2]);
    tags.selectGeneral(1);
    expect(tags.selected).toEqual([1]);
  });

  it('filter derived reflects selection without a mode field', () => {
    tags.selectGeneral(3);
    tags.selectGeneral(7, { additive: true });
    // v0.7.4: `tags` key is always included on the filter object
    // so the API client can distinguish "nothing selected → match
    // nothing" from the legacy unfiltered path. `severityTags` still
    // uses `undefined` for "no severity filter" since severity
    // doesn't share the empty-means-nothing rule.
    expect(tags.filter).toEqual({ tags: [3, 7], severityTags: undefined });
  });

  it('filter derived sends an empty tags array when no general tag is selected', () => {
    // Empty selection → `tags: []` → the API client sends `?tags=`
    // which the backend reads as "match nothing". The pre-v0.7.4
    // contract was `tags: undefined`, which the backend read as "no
    // filter, every session". Regression guard for Dave's 2026-04-23
    // sidebar change.
    expect(tags.filter.tags).toEqual([]);
  });

  it('clearSelection empties the set', () => {
    tags.selected = [1, 2];
    tags.clearSelection();
    expect(tags.selected).toEqual([]);
    expect(tags.hasFilter).toBe(false);
  });

  it('selectAllGeneral picks every general-group id and leaves severity alone', () => {
    // v0.7.4: the "All" button in the panel header hydrates
    // `selected` with the full general-tag roster. Severity tags are
    // filtered out — they ride on a separate axis.
    tags.list = [
      tag({ id: 1, tag_group: 'general' }),
      tag({ id: 2, tag_group: 'general' }),
      tag({ id: 8, tag_group: 'severity' }),
      tag({ id: 9, tag_group: 'severity' })
    ];
    tags.selectedSeverity = [9];
    tags.selectAllGeneral();
    expect(tags.selected).toEqual([1, 2]);
    // Severity axis untouched.
    expect(tags.selectedSeverity).toEqual([9]);
  });

  it('generalList and severityList partition by tag_group', () => {
    tags.list = [
      tag({ id: 1, name: 'infra', tag_group: 'general', sort_order: 0 }),
      tag({ id: 2, name: 'Blocker', tag_group: 'severity', sort_order: 1 }),
      tag({ id: 3, name: 'Low', tag_group: 'severity', sort_order: 4 }),
      tag({ id: 4, name: 'docs', tag_group: 'general', sort_order: 0 })
    ];
    expect(tags.generalList.map((t) => t.id)).toEqual([1, 4]);
    // Severity list sorted by sort_order so Blocker precedes Low.
    expect(tags.severityList.map((t) => t.id)).toEqual([2, 3]);
  });

  it('selectSeverity mirrors Finder rules on the severity axis and stays independent of general', () => {
    tags.selectSeverity(5);
    expect(tags.selectedSeverity).toEqual([5]);
    expect(tags.hasSeverityFilter).toBe(true);
    expect(tags.hasFilter).toBe(false);
    // Plain click on the sole severity clears it.
    tags.selectSeverity(5);
    expect(tags.selectedSeverity).toEqual([]);
    expect(tags.hasSeverityFilter).toBe(false);
    // Shift-click is additive on the severity axis too — a session
    // has exactly one severity, so multiple selected severities
    // combine as OR on the server.
    tags.selectSeverity(8);
    tags.selectSeverity(9, { additive: true });
    expect(tags.selectedSeverity).toEqual([8, 9]);
  });

  it('filter derived passes severityTags when a severity is selected', () => {
    tags.selectGeneral(1);
    tags.selectSeverity(9);
    expect(tags.filter).toEqual({ tags: [1], severityTags: [9] });
  });

  it('clearSeveritySelection only clears severity axis', () => {
    tags.selected = [1];
    tags.selectedSeverity = [9, 10];
    tags.clearSeveritySelection();
    expect(tags.selected).toEqual([1]);
    expect(tags.selectedSeverity).toEqual([]);
  });

  it('remove drops selection in both axes for the removed tag', async () => {
    tags.list = [
      tag({ id: 1, tag_group: 'general' }),
      tag({ id: 9, tag_group: 'severity' })
    ];
    tags.selected = [1];
    tags.selectedSeverity = [9];
    queueResponses([{ ok: true, status: 204, body: '' }]);
    const ok = await tags.remove(9);
    expect(ok).toBe(true);
    expect(tags.selectedSeverity).toEqual([]);
    // Other axis untouched.
    expect(tags.selected).toEqual([1]);
  });

  it('SEVERITY_NONE_ID flows through selectSeverity and filter like a real id', () => {
    // Sentinel starts with the same Finder semantics as real tag ids.
    tags.selectSeverity(SEVERITY_NONE_ID);
    expect(tags.selectedSeverity).toEqual([SEVERITY_NONE_ID]);
    expect(tags.hasSeverityFilter).toBe(true);
    // Shift-click pairs the sentinel with a real severity.
    tags.selectSeverity(9, { additive: true });
    expect(tags.selectedSeverity).toEqual([SEVERITY_NONE_ID, 9]);
    // Derived filter passes the sentinel straight through — api/sessions
    // builds `severity_tags=-1,9` and the backend maps -1 to its
    // NOT EXISTS branch.
    expect(tags.filter.severityTags).toEqual([SEVERITY_NONE_ID, 9]);
  });

  it('togglePanel flips and persists the collapsed state', () => {
    expect(tags.panelCollapsed).toBe(false);
    tags.togglePanel();
    expect(tags.panelCollapsed).toBe(true);
    expect(localStorage.getItem('bearings.tagFilterPanel.collapsed')).toBe('1');
    tags.togglePanel();
    expect(tags.panelCollapsed).toBe(false);
    expect(localStorage.getItem('bearings.tagFilterPanel.collapsed')).toBe('0');
  });
});
