import type { TodoItem } from './core';
import { jsonFetch, voidFetch } from './core';

export type Session = {
  id: string;
  created_at: string;
  updated_at: string;
  working_dir: string;
  model: string;
  title: string | null;
  description: string | null;
  max_budget_usd: number | null;
  total_cost_usd: number;
  message_count: number;
  session_instructions: string | null;
  /** Persisted PermissionMode from migration 0012. `null` means the
   * user never picked one and the UI should fall back to 'default'.
   * Agent connection reads this on (re)connect so plan / auto-edit /
   * bypass choices survive reloads. */
  permission_mode: 'default' | 'plan' | 'acceptEdits' | 'bypassPermissions' | null;
  /** Most recent ContextUsage snapshot (migration 0013). Null until
   * the session has completed at least one assistant turn. Live
   * updates flow through the `context_usage` WS event; these cached
   * fields back the first paint on load / reconnect so the meter
   * isn't empty between turns. */
  last_context_pct: number | null;
  last_context_tokens: number | null;
  last_context_max: number | null;
  /** Lifecycle flag (migration 0015). Null = open (default). Non-null
   * ISO timestamp = closed — the sidebar sinks the row into the
   * collapsed "Closed" group. Reorg ops touching a closed session
   * auto-clear this on the backend, so the UI doesn't need to
   * force-reopen on merge/move/split. */
  closed_at: string | null;
  /** v0.4.0 session-kind discriminator (migration 0016). 'chat' is
   * the historical default rendered as a conversation; 'checklist'
   * renders a structured list view instead. The right-pane and the
   * WS handler both gate on this field. */
  kind: 'chat' | 'checklist';
  /** v0.5.0 per-item paired-chat pointer (migration 0017). Null on
   * every plain chat session; non-null means the chat was spawned
   * from a specific checklist item via "💬 Work on this" and the
   * backend injects a `checklist_context` layer into the prompt on
   * every turn. Conversation.svelte renders a breadcrumb when this
   * is set. */
  checklist_item_id: number | null;
  /** View-tracking pair (migration 0020). `last_completed_at` is the
   * ISO timestamp of the most recent MessageComplete persisted for
   * this session; null until the first assistant turn finishes. */
  last_completed_at: string | null;
  /** ISO timestamp of the last time the user focused / selected this
   * session (via POST /{id}/viewed). Null means "never viewed." The
   * sidebar paints an amber "finished but unviewed" dot when
   * `last_completed_at` is non-null and either this is null or
   * precedes it. */
  last_viewed_at: string | null;
  /** v0.2.14 / migration 0021: every tag id attached to this session,
   * in no particular order. Lets the sidebar render the medallion row
   * (severity shield + per-general-tag icon) by joining against the
   * in-memory tags store — no per-row fetch. Empty on pre-0021
   * snapshots that slipped through without a severity backfill. */
  tag_ids: number[];
  /** Migration 0022 / v0.9.1: the session-pinned flag the context-menu
   * `session.pin` action flips. Defaults to false on rows created
   * before the migration. Currently informational — the sidebar
   * doesn't re-sort on pinned (that's a Phase 4a.3 polish pass); the
   * flag exists so the menu can render "Unpin" on already-pinned rows
   * and so the frontend round-trips the column through PATCH without
   * silently dropping it. */
  pinned: boolean;
};

export type SessionCreate = {
  working_dir: string;
  model: string;
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
  /** v0.2.13 requires at least one tag on every new session. */
  tag_ids: number[];
  /** v0.4.0 kind discriminator. Omit or set 'chat' for a normal
   * conversation session; 'checklist' creates the structured-list
   * variant (the server also inserts the companion checklists row in
   * the same transaction). */
  kind?: 'chat' | 'checklist';
};

export type SessionUpdate = {
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
  session_instructions?: string | null;
  /** v0.9.1 / migration 0022: flip the sidebar-pin flag. Pure UX — no
   * runner drop. `null` is "don't touch"; to unpin an already-pinned
   * session, POST `false`. */
  pinned?: boolean | null;
  /** v0.9.1: "Change model for continuation" (plan decision §2.1) —
   * mutates in place so subsequent turns use the new model while past
   * turns keep their original attribution. The backend drops the
   * cached SDK subprocess on any model change so the next turn boots
   * against the new model. Past cost rows are already per-turn. */
  model?: string | null;
};

export type Message = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  thinking: string | null;
  created_at: string;
  /** Per-turn token counts captured from `ResultMessage.usage` when the
   * row was first persisted. Null on user rows and on assistant rows
   * created before migration 0011 landed. The Conversation view uses
   * the aggregate /tokens endpoint rather than summing these, so these
   * are informational — exposed here so future UI can show per-turn
   * breakdowns without another round-trip. */
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  cache_creation_tokens?: number | null;
  /** Message flag pair (migration 0023, Phase 8 of the context-menu
   * plan). `pinned` floats the row in the conversation header without
   * affecting the prompt. `hidden_from_context` drops the row from the
   * context window assembled for the next agent turn — the row still
   * renders in the conversation (greyed) so the user can toggle it
   * back. Both default false via the column default. */
  pinned?: boolean;
  hidden_from_context?: boolean;
};

/** Aggregate per-session token counts served by
 * `GET /sessions/{id}/tokens`. Every field is a non-negative int —
 * the server COALESCE-SUMs NULL rows to 0, so "session with zero
 * assistant turns" and "session full of null rows" both return all
 * zeros rather than null. */
export type TokenTotals = {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
};

export type ToolCall = {
  id: string;
  session_id: string;
  message_id: string | null;
  name: string;
  input: string; // JSON string as stored in DB
  output: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type SessionFilter = {
  /** General-group tag ids. Multiple ids are AND-combined — a session
   * must carry every selected tag to appear. The old Any/All toggle
   * was removed in the v0.2.15 sidebar redesign; the wire format
   * still uses `mode=all`, hardcoded in `listSessions`. */
  tags?: number[];
  /** v0.2.14 severity axis (migration 0021). Severity tags are a
   * separate user-editable group; backend always OR-within-group
   * because each session carries exactly one severity. Combined with
   * `tags` via AND. Omit or pass `[]` for no severity filter. */
  severityTags?: number[];
};

export function listRunningSessions(
  fetchImpl: typeof fetch = fetch
): Promise<string[]> {
  return jsonFetch<string[]>(fetchImpl, '/api/sessions/running');
}

export function listSessions(
  filter: SessionFilter = {},
  fetchImpl: typeof fetch = fetch
): Promise<Session[]> {
  const tagIds = filter.tags ?? [];
  const severityIds = filter.severityTags ?? [];
  // No filter at all → hit the bare path so the server skips the
  // WHERE-clause builder entirely. Any filter present → build the
  // query string with only the populated axes.
  if (tagIds.length === 0 && severityIds.length === 0) {
    return jsonFetch<Session[]>(fetchImpl, '/api/sessions');
  }
  const params = new URLSearchParams();
  if (tagIds.length > 0) {
    params.set('tags', tagIds.join(','));
    // Always AND — the Any/All toggle was removed in v0.2.15. The
    // backend route still defaults to 'any' when `mode` is omitted, so
    // we pin it explicitly here rather than relying on the default.
    params.set('mode', 'all');
  }
  if (severityIds.length > 0) {
    params.set('severity_tags', severityIds.join(','));
  }
  return jsonFetch<Session[]>(fetchImpl, `/api/sessions?${params}`);
}

export function getSession(
  id: string,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, `/api/sessions/${id}`);
}

export function createSession(
  body: SessionCreate,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, '/api/sessions', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export async function deleteSession(
  id: string,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  await jsonFetch<{ deleted: boolean }>(fetchImpl, `/api/sessions/${id}`, {
    method: 'DELETE'
  });
}

export function updateSession(
  id: string,
  patch: SessionUpdate,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, `/api/sessions/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch)
  });
}

/** Mark the session closed — the sidebar sinks it into the collapsed
 * "Closed" group on the next render. Idempotent: the server refreshes
 * the `closed_at` timestamp on a second call. Returns the refreshed
 * session row. */
export function closeSession(
  id: string,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, `/api/sessions/${id}/close`, {
    method: 'POST'
  });
}

/** Reopen a previously closed session. Idempotent on already-open
 * sessions. Returns the refreshed session row. */
export function reopenSession(
  id: string,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, `/api/sessions/${id}/reopen`, {
    method: 'POST'
  });
}

/** Stamp `last_viewed_at` on the session so the sidebar clears the
 * "finished but unviewed" amber dot. Fired on session select and on
 * `visibilitychange` → visible while a session is selected. Does not
 * change sort position; the server returns the refreshed row for the
 * caller to merge into local state. Idempotent. */
export function markSessionViewed(
  id: string,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, `/api/sessions/${id}/viewed`, {
    method: 'POST'
  });
}

export function listMessages(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<Message[]> {
  return jsonFetch<Message[]>(fetchImpl, `/api/sessions/${sessionId}/messages`);
}

export type MessagePage = {
  /** Oldest-first so the caller can prepend/append directly. */
  messages: Message[];
  /** True if the server returned exactly `limit` rows — there may be
   * more older messages beyond this page. */
  hasMore: boolean;
};

export async function listMessagesPage(
  sessionId: string,
  opts: { before?: string; limit?: number } = {},
  fetchImpl: typeof fetch = fetch
): Promise<MessagePage> {
  const limit = opts.limit ?? 50;
  const params = new URLSearchParams({ limit: String(limit) });
  if (opts.before) params.set('before', opts.before);
  // Server sends newest-first when `limit` is set. Reverse once so
  // the caller sees the familiar oldest-first ordering.
  const raw = await jsonFetch<Message[]>(
    fetchImpl,
    `/api/sessions/${sessionId}/messages?${params}`
  );
  return { messages: raw.reverse(), hasMore: raw.length === limit };
}

export function listToolCalls(
  sessionId: string,
  opts: { messageIds?: string[] } = {},
  fetchImpl: typeof fetch = fetch
): Promise<ToolCall[]> {
  // Pass `messageIds` to scope the response to the currently-visible
  // conversation page — the backend filters by `message_id IN (...)`
  // and drops orphan rows, which keeps the payload O(page) instead of
  // O(session history). Omitting `messageIds` returns every tool_call
  // for the session (legacy behavior, still used by export/checkpoint
  // paths if they ever call this wrapper). An empty array is a valid
  // filter meaning "no visible messages" — the server returns [] for
  // that, which matches what the store would render anyway.
  let url = `/api/sessions/${sessionId}/tool_calls`;
  if (opts.messageIds !== undefined) {
    const params = new URLSearchParams();
    // FastAPI parses repeated `message_ids=` query params as a list.
    // URLSearchParams.append is the idiomatic way to emit them; a
    // comma-joined single param would not round-trip through Query().
    for (const id of opts.messageIds) params.append('message_ids', id);
    url += `?${params}`;
  }
  return jsonFetch<ToolCall[]>(fetchImpl, url);
}

export function getSessionTokens(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<TokenTotals> {
  return jsonFetch<TokenTotals>(fetchImpl, `/api/sessions/${sessionId}/tokens`);
}

/** Reply shape for `GET /sessions/{id}/todos`. `todos` is `null` when
 * the session has never invoked TodoWrite; an empty array means the
 * agent explicitly cleared its list. The LiveTodos widget uses the
 * distinction to render "no active todo session" vs. "todo session
 * active but currently empty." Live updates after first paint come
 * via the `todo_write_update` WS event. */
export type SessionTodos = {
  todos: TodoItem[] | null;
};

export function getSessionTodos(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<SessionTodos> {
  return jsonFetch<SessionTodos>(fetchImpl, `/api/sessions/${sessionId}/todos`);
}

/** Result shape shared by the reorg/move and reorg/split endpoints.
 * `warnings` is always present but empty until Slice 7 wires the
 * tool-call-group detector in — keep the field in view now so the
 * UI can handle it without a second round of type plumbing. */
export type ReorgWarning = {
  code: string;
  message: string;
  details: Record<string, string>;
};

export type ReorgMoveResult = {
  moved: number;
  tool_calls_followed: number;
  warnings: ReorgWarning[];
  /** The `reorg_audits` row the server wrote for this op, or `null`
   * when no divider was recorded (idempotent no-op move, or merge
   * with `delete_source=true`). The undo handler passes this back to
   * `deleteReorgAudit` so the inline divider goes away when the
   * inverse move lands. */
  audit_id: number | null;
};

export type ReorgMoveRequest = {
  target_session_id: string;
  message_ids: string[];
};

export type NewSessionSpec = {
  title: string;
  description?: string | null;
  tag_ids: number[];
  model?: string | null;
  working_dir?: string | null;
};

export type ReorgSplitRequest = {
  after_message_id: string;
  new_session: NewSessionSpec;
};

export type ReorgSplitResult = {
  session: Session;
  result: ReorgMoveResult;
};

/** Cherry-pick message ids out of `sourceId` into `targetSessionId`.
 * Both sessions must exist; source != target. Server stops any live
 * runner on both sides so the next turn rebuilds against the new
 * DB state. Tool-call rows anchored to a moved message follow. */
export function reorgMove(
  sourceId: string,
  body: ReorgMoveRequest,
  fetchImpl: typeof fetch = fetch
): Promise<ReorgMoveResult> {
  return jsonFetch<ReorgMoveResult>(fetchImpl, `/api/sessions/${sourceId}/reorg/move`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

/** Split `sourceId` at `after_message_id`: creates a new session
 * (inheriting model / working_dir from the source unless overridden)
 * and moves every chronologically-later message into it in one
 * transaction. Returns the new session row + the move result. */
export function reorgSplit(
  sourceId: string,
  body: ReorgSplitRequest,
  fetchImpl: typeof fetch = fetch
): Promise<ReorgSplitResult> {
  return jsonFetch<ReorgSplitResult>(fetchImpl, `/api/sessions/${sourceId}/reorg/split`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export type ReorgMergeRequest = {
  target_session_id: string;
  /** When true the source session is deleted after the move (in that
   * order, to avoid the `ON DELETE CASCADE` on `messages.session_id`
   * swallowing the freshly-moved rows). */
  delete_source: boolean;
};

export type ReorgMergeResult = {
  moved: number;
  tool_calls_followed: number;
  warnings: ReorgWarning[];
  /** Null when the merge op wrote no audit row — either because
   * nothing moved, or because `delete_source=true` would have caused
   * the cascade to drop the row anyway. */
  audit_id: number | null;
  /** Echoes the request flag on success. False + `delete_source=true`
   * would only happen on a server-side glitch; the current server
   * always honors the flag. */
  deleted_source: boolean;
};

/** Fold every message on `sourceId` into `targetSessionId` in a
 * single transaction, optionally dropping the now-empty source. An
 * empty source is a legitimate no-op (moves 0); `delete_source=true`
 * still removes it so the UI can clear orphaned empty sessions from
 * the sidebar with one click. */
export function reorgMerge(
  sourceId: string,
  body: ReorgMergeRequest,
  fetchImpl: typeof fetch = fetch
): Promise<ReorgMergeResult> {
  return jsonFetch<ReorgMergeResult>(fetchImpl, `/api/sessions/${sourceId}/reorg/merge`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

/** One row in the persistent reorg audit trail for `sourceId`.
 * `target_session_id` is `null` when the target was deleted after
 * the op ran (FK is `ON DELETE SET NULL`) — use
 * `target_title_snapshot` to render "(deleted session)" in that
 * case. `created_at` is the ISO timestamp of the op. */
export type ReorgAudit = {
  id: number;
  source_session_id: string;
  target_session_id: string | null;
  target_title_snapshot: string | null;
  message_count: number;
  op: 'move' | 'split' | 'merge';
  created_at: string;
};

/** Oldest-first list of every audit divider attached to `sessionId`.
 * 404s when the session itself is gone rather than returning `[]` so
 * callers don't silently paper over a stale id. */
export function listReorgAudits(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<ReorgAudit[]> {
  return jsonFetch<ReorgAudit[]>(fetchImpl, `/api/sessions/${sessionId}/reorg/audits`);
}

/** Remove an audit divider, scoped to `sessionId` — the server 404s
 * on a cross-session id so a stale URL can't delete audits belonging
 * to another session. Idempotent from the caller's perspective: a
 * second delete on the same id returns 404, not success, because the
 * row's already gone. */
export function deleteReorgAudit(
  sessionId: string,
  auditId: number,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  return voidFetch(fetchImpl, `/api/sessions/${sessionId}/reorg/audits/${auditId}`, {
    method: 'DELETE'
  });
}
