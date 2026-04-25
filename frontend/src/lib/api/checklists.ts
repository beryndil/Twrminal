/** API bindings for checklist sessions (v0.4.0, Slice 3).
 *
 * Every function maps one-to-one to an endpoint in
 * `routes_checklists.py`. The server rejects these on non-checklist
 * sessions with a 400 — callers should gate the call on
 * `session.kind === 'checklist'` before invoking.
 */

import { jsonFetch, voidFetch } from './core';
import type { Session } from './sessions';

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
  /** v0.5.0 paired-chat pointer (migration 0017). Null until the user
   * first clicks "💬 Work on this"; non-null means the item has a
   * chat session dedicated to it. ChecklistView uses this to toggle
   * the per-item button between "Work on this" (spawn) and
   * "Continue working" (navigate). */
  chat_session_id: string | null;
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

/** Body for `POST /sessions/{id}/checklist/items/{item_id}/chat`. All
 * fields optional — the server inherits `working_dir` / `model` /
 * `tag_ids` from the parent checklist session when omitted, and
 * defaults the title to the item label. */
export type PairedChatCreate = {
  working_dir?: string | null;
  model?: string | null;
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
  tag_ids?: number[];
};

/** Spawn (or return the existing) chat session paired to a checklist
 * item. Idempotent: a second call returns the same session id, so a
 * double-click on "💬 Work on this" doesn't create dangling chats.
 * The returned `Session` carries `kind='chat'` + a non-null
 * `checklist_item_id` pointing back at the source item. */
export function spawnPairedChat(
  sessionId: string,
  itemId: number,
  body: PairedChatCreate = {},
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(
    fetchImpl,
    `/api/sessions/${sessionId}/checklist/items/${itemId}/chat`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }
  );
}

/** Resolve the existing paired chat for a checklist item. 404s when
 * the item has never been worked on. Prefer this over inspecting
 * `ChecklistItem.chat_session_id` when you need the full session row;
 * the pointer alone is enough to decide button state. */
export function getPairedChat(
  sessionId: string,
  itemId: number,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(
    fetchImpl,
    `/api/sessions/${sessionId}/checklist/items/${itemId}/chat`
  );
}

// --- autonomous runner ----------------------------------------------
//
// Backed by `POST /run`, `GET /run`, `DELETE /run` on the checklist.
// Server implementation at `routes_checklists.py`; design note under
// `TODO.md` § "Autonomous checklist execution".

/** Optional per-run caps posted to `POST /sessions/{id}/checklist/run`.
 * Omit fields (or the whole body) to use the driver's conservative
 * defaults: 50 items / 5 legs / depth 3 / 60% handoff threshold,
 * spawn-per-item, halt-on-first-failure.
 *
 * `failure_policy` and `visit_existing_sessions` together encode
 * "tour mode": visit each item's pre-linked chat session and advance
 * past failures rather than halting the whole run. The UI exposes
 * both behind a single "Tour mode" checkbox (see `ChecklistView`).
 * Specifying them individually via this type is fine for callers
 * (tests, scripts) that want one without the other. */
export type AutoRunStart = {
  max_items_per_run?: number | null;
  max_legs_per_item?: number | null;
  max_followup_depth?: number | null;
  /** `'halt'` (default) ends the run on the first failed item;
   * `'skip'` records the failure on the item, leaves it unchecked,
   * and advances to the next item. */
  failure_policy?: 'halt' | 'skip' | null;
  /** When `true`, leg 1 of each item reuses the session linked via
   * `checklist_items.chat_session_id` instead of spawning a fresh
   * paired chat. Items with no linked session are skipped (counted
   * in `items_skipped`, run advances). Handoff legs still spawn
   * fresh. */
  visit_existing_sessions?: boolean | null;
};

/** Shape returned by all three /run endpoints.
 *
 * `state` is the primary discriminator:
 *  - `"running"` → driver task is active. `items_completed` /
 *    `items_failed` / `legs_spawned` are live counters.
 *  - `"finished"` → driver reached a terminal outcome. `outcome`
 *    matches the server's `DriverOutcome` string values:
 *    `completed`, `halted_empty`, `halted_failure`,
 *    `halted_max_items`, `halted_stop`. On `halted_failure`,
 *    `failed_item_id` + `failure_reason` carry the detail (the
 *    reason is also persisted into `ChecklistItem.notes` with an
 *    `[auto-run]` prefix).
 *  - `"errored"` → driver task raised an uncaught exception;
 *    `error` holds `type(exc).__name__: str(exc)`. Rare — every
 *    expected failure surfaces as `state=finished` /
 *    `outcome=halted_failure` through the state machine. */
export type AutoRunStatus = {
  state: 'running' | 'finished' | 'errored';
  items_completed?: number | null;
  items_failed?: number | null;
  legs_spawned?: number | null;
  outcome?: string | null;
  failed_item_id?: number | null;
  failure_reason?: string | null;
  error?: string | null;
};

/** Launch the autonomous driver against this checklist. Returns the
 * initial `running` status snapshot. Second call while one is
 * running returns 409 — the client should GET the status or DELETE
 * the run first. */
export function startAutoRun(
  sessionId: string,
  body: AutoRunStart = {},
  fetchImpl: typeof fetch = fetch
): Promise<AutoRunStatus> {
  return jsonFetch<AutoRunStatus>(fetchImpl, `/api/sessions/${sessionId}/checklist/run`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

/** Poll the autonomous driver's current state. Raises on 404 when
 * no driver has ever been started for this checklist — callers that
 * want a `null`-on-404 shape should catch and translate. */
export function getAutoRun(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<AutoRunStatus> {
  return jsonFetch<AutoRunStatus>(fetchImpl, `/api/sessions/${sessionId}/checklist/run`);
}

/** Stop a running driver AND forget a finished one in a single call.
 * Idempotent: 204 whether there was a live driver or not. */
export function stopAutoRun(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  return voidFetch(fetchImpl, `/api/sessions/${sessionId}/checklist/run`, {
    method: 'DELETE'
  });
}
