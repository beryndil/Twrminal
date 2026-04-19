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
  max_budget_usd: number | null;
};

export type SessionCreate = {
  working_dir: string;
  model: string;
  title?: string | null;
  max_budget_usd?: number | null;
};

export type Message = {
  id: string;
  session_id: string;
  role: string;
  content: string;
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
};
export type ErrorEvent = { type: 'error'; session_id: string; message: string };

export type AgentEvent =
  | TokenEvent
  | UserMessageEvent
  | ToolCallStartEvent
  | ToolCallEndEvent
  | MessageStartEvent
  | MessageCompleteEvent
  | ErrorEvent;

async function jsonFetch<T>(
  fetchImpl: typeof fetch,
  url: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetchImpl(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${init?.method ?? 'GET'} ${url} → ${res.status}: ${body}`);
  }
  return (await res.json()) as T;
}

export function fetchHealth(fetchImpl: typeof fetch = fetch): Promise<HealthResponse> {
  return jsonFetch<HealthResponse>(fetchImpl, '/api/health');
}

export function listSessions(fetchImpl: typeof fetch = fetch): Promise<Session[]> {
  return jsonFetch<Session[]>(fetchImpl, '/api/sessions');
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

export function listMessages(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<Message[]> {
  return jsonFetch<Message[]>(fetchImpl, `/api/sessions/${sessionId}/messages`);
}

export function listToolCalls(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<ToolCall[]> {
  return jsonFetch<ToolCall[]>(fetchImpl, `/api/sessions/${sessionId}/tool_calls`);
}

export function openAgentSocket(sessionId: string): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return new WebSocket(`${proto}://${window.location.host}/ws/sessions/${sessionId}`);
}
