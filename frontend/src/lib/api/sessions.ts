import { jsonFetch } from './core';

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
