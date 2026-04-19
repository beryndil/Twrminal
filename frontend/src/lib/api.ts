export type HealthResponse = {
  auth: string;
  version: string;
};

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
};

export type SessionCreate = {
  working_dir: string;
  model: string;
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
};

export type SessionUpdate = {
  title?: string | null;
  description?: string | null;
  max_budget_usd?: number | null;
};

export type Message = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  thinking: string | null;
  created_at: string;
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

export type TokenEvent = { type: 'token'; session_id: string; text: string };
export type ThinkingEvent = { type: 'thinking'; session_id: string; text: string };
export type UserMessageEvent = { type: 'user_message'; session_id: string; content: string };
export type ToolCallStartEvent = {
  type: 'tool_call_start';
  session_id: string;
  tool_call_id: string;
  name: string;
  input: Record<string, unknown>;
};
export type ToolCallEndEvent = {
  type: 'tool_call_end';
  session_id: string;
  tool_call_id: string;
  ok: boolean;
  output: string | null;
  error: string | null;
};
export type MessageStartEvent = {
  type: 'message_start';
  session_id: string;
  message_id: string;
};
export type MessageCompleteEvent = {
  type: 'message_complete';
  session_id: string;
  message_id: string;
  cost_usd: number | null;
};
export type ErrorEvent = { type: 'error'; session_id: string; message: string };

export type AgentEvent =
  | TokenEvent
  | ThinkingEvent
  | UserMessageEvent
  | ToolCallStartEvent
  | ToolCallEndEvent
  | MessageStartEvent
  | MessageCompleteEvent
  | ErrorEvent;

const TOKEN_STORAGE_KEY = 'twrminal:token';

/** Reads the auth token from localStorage. Set via devtools:
 * `localStorage.setItem('twrminal:token', 'your-token')`. A full
 * in-app settings UI lands in a later slice. */
function readAuthToken(): string | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function withAuth(init?: RequestInit): RequestInit | undefined {
  const token = readAuthToken();
  if (!token) return init;
  const headers = new Headers(init?.headers);
  headers.set('Authorization', `Bearer ${token}`);
  return { ...init, headers };
}

let authFailureHandler: (() => void) | null = null;

/** Register a callback fired whenever an API call sees a 401 — the auth
 * store uses this to flip itself to `invalid` without a circular import. */
export function onAuthFailure(cb: () => void): void {
  authFailureHandler = cb;
}

async function jsonFetch<T>(
  fetchImpl: typeof fetch,
  url: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetchImpl(url, withAuth(init));
  if (res.status === 401 && authFailureHandler) {
    authFailureHandler();
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${init?.method ?? 'GET'} ${url} → ${res.status}: ${body}`);
  }
  return (await res.json()) as T;
}

export function fetchHealth(fetchImpl: typeof fetch = fetch): Promise<HealthResponse> {
  return jsonFetch<HealthResponse>(fetchImpl, '/api/health');
}

export type SessionFilter = {
  tags?: number[];
  mode?: 'any' | 'all';
};

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

export type SearchHit = {
  message_id: string;
  session_id: string;
  session_title: string | null;
  model: string;
  role: string;
  snippet: string;
  created_at: string;
};

export type Tag = {
  id: number;
  name: string;
  color: string | null;
  pinned: boolean;
  sort_order: number;
  created_at: string;
  session_count: number;
};

export type TagCreate = {
  name: string;
  color?: string | null;
  pinned?: boolean;
  sort_order?: number;
};

export type TagUpdate = {
  name?: string;
  color?: string | null;
  pinned?: boolean;
  sort_order?: number;
};

export function listTags(fetchImpl: typeof fetch = fetch): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, '/api/tags');
}

export function listSessionTags(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, `/api/sessions/${sessionId}/tags`);
}

export function createTag(
  body: TagCreate,
  fetchImpl: typeof fetch = fetch
): Promise<Tag> {
  return jsonFetch<Tag>(fetchImpl, '/api/tags', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export function updateTag(
  id: number,
  patch: TagUpdate,
  fetchImpl: typeof fetch = fetch
): Promise<Tag> {
  return jsonFetch<Tag>(fetchImpl, `/api/tags/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch)
  });
}

export async function deleteTag(
  id: number,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  const res = await fetchImpl(`/api/tags/${id}`, withAuth({ method: 'DELETE' }));
  if (res.status === 401 && authFailureHandler) authFailureHandler();
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`DELETE /api/tags/${id} → ${res.status}: ${body}`);
  }
}

export function attachSessionTag(
  sessionId: string,
  tagId: number,
  fetchImpl: typeof fetch = fetch
): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, `/api/sessions/${sessionId}/tags/${tagId}`, {
    method: 'POST'
  });
}

export function detachSessionTag(
  sessionId: string,
  tagId: number,
  fetchImpl: typeof fetch = fetch
): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, `/api/sessions/${sessionId}/tags/${tagId}`, {
    method: 'DELETE'
  });
}

export function searchHistory(
  query: string,
  limit = 50,
  fetchImpl: typeof fetch = fetch
): Promise<SearchHit[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return jsonFetch<SearchHit[]>(fetchImpl, `/api/history/search?${params}`);
}

export type SessionExport = {
  session: Session;
  messages: Message[];
  tool_calls: ToolCall[];
};

export function exportSession(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<SessionExport> {
  return jsonFetch<SessionExport>(fetchImpl, `/api/sessions/${sessionId}/export`);
}

export function importSession(
  payload: SessionExport,
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(fetchImpl, '/api/sessions/import', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export function openAgentSocket(sessionId: string): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const token = readAuthToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return new WebSocket(
    `${proto}://${window.location.host}/ws/sessions/${sessionId}${query}`
  );
}
