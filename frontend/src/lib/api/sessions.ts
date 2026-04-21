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
};

export type SessionCreate = {
  working_dir: string;
  model: string;
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
  /** v0.2.13 requires at least one tag on every new session. */
  tag_ids: number[];
};

export type SessionUpdate = {
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
  session_instructions?: string | null;
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
  tags?: number[];
  mode?: 'any' | 'all';
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
  if (tagIds.length === 0) return jsonFetch<Session[]>(fetchImpl, '/api/sessions');
  const params = new URLSearchParams({
    tags: tagIds.join(','),
    mode: filter.mode ?? 'any'
  });
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
  fetchImpl: typeof fetch = fetch
): Promise<ToolCall[]> {
  return jsonFetch<ToolCall[]>(fetchImpl, `/api/sessions/${sessionId}/tool_calls`);
}

export function getSessionTokens(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<TokenTotals> {
  return jsonFetch<TokenTotals>(fetchImpl, `/api/sessions/${sessionId}/tokens`);
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
