/** API bindings for checklist sessions (v0.4.0, Slice 3).
 *
 * Every function maps one-to-one to an endpoint in
 * `routes_checklists.py`. The server rejects these on non-checklist
 * sessions with a 400 — callers should gate the call on
 * `session.kind === 'checklist'` before invoking.
 */

import { jsonFetch, voidFetch } from './core';

export type ChecklistItem = {
  id: number;
  checklist_id: string;
  parent_item_id: number | null;
  label: string;
  notes: string | null;
  /** ISO timestamp set when the user checks the box; `null` when
   * unchecked. The store derives `checked: boolean` from `!= null`. */
  checked_at: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type Checklist = {
  session_id: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** Flat list in (sort_order, id) order. Nested children are
   * recovered client-side via `parent_item_id` — a single flat list
   * is cheaper to ship than a recursive CTE and Slice 3 doesn't yet
   * render nesting. */
  items: ChecklistItem[];
};

export type ChecklistUpdate = {
  notes?: string | null;
};

export type ItemCreate = {
  label: string;
  notes?: string | null;
  parent_item_id?: number | null;
  sort_order?: number | null;
};

export type ItemUpdate = {
  label?: string | null;
  notes?: string | null;
  parent_item_id?: number | null;
  sort_order?: number | null;
};

export function getChecklist(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<Checklist> {
  return jsonFetch<Checklist>(fetchImpl, `/api/sessions/${sessionId}/checklist`);
}

export function updateChecklist(
  sessionId: string,
  patch: ChecklistUpdate,
  fetchImpl: typeof fetch = fetch
): Promise<Checklist> {
  return jsonFetch<Checklist>(fetchImpl, `/api/sessions/${sessionId}/checklist`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch)
  });
}

export function createItem(
  sessionId: string,
  body: ItemCreate,
  fetchImpl: typeof fetch = fetch
): Promise<ChecklistItem> {
  return jsonFetch<ChecklistItem>(fetchImpl, `/api/sessions/${sessionId}/checklist/items`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export function updateItem(
  sessionId: string,
  itemId: number,
  patch: ItemUpdate,
  fetchImpl: typeof fetch = fetch
): Promise<ChecklistItem> {
  return jsonFetch<ChecklistItem>(
    fetchImpl,
    `/api/sessions/${sessionId}/checklist/items/${itemId}`,
    {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(patch)
    }
  );
}

export function toggleItem(
  sessionId: string,
  itemId: number,
  checked: boolean,
  fetchImpl: typeof fetch = fetch
): Promise<ChecklistItem> {
  return jsonFetch<ChecklistItem>(
    fetchImpl,
    `/api/sessions/${sessionId}/checklist/items/${itemId}/toggle`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ checked })
    }
  );
}

export function deleteItem(
  sessionId: string,
  itemId: number,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  return voidFetch(fetchImpl, `/api/sessions/${sessionId}/checklist/items/${itemId}`, {
    method: 'DELETE'
  });
}

export type ReorderResult = { reordered: number };

export function reorderItems(
  sessionId: string,
  itemIds: number[],
  fetchImpl: typeof fetch = fetch
): Promise<ReorderResult> {
  return jsonFetch<ReorderResult>(fetchImpl, `/api/sessions/${sessionId}/checklist/reorder`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ item_ids: itemIds })
  });
}
