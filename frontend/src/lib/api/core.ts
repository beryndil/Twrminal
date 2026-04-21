export type HealthResponse = {
  auth: string;
  version: string;
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
/** Incremental chunk of a tool's output. Reducer appends `delta` to
 * the matching tool call's `output` string. The backend line-buffers
 * at the source so chunks are always on safe boundaries (newline /
 * complete UTF-8 codepoint). Must arrive before the `tool_call_end`
 * for the same `tool_call_id` — the reducer drops any delta whose
 * target call has already finished (via `_seq` ordering). */
export type ToolOutputDeltaEvent = {
  type: 'tool_output_delta';
  session_id: string;
  tool_call_id: string;
  delta: string;
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

/** Ground-truth snapshot of the server's runner state, sent once per
 * WebSocket connection right after replay. Lets a reconnecting client
 * reconcile stale `streamingActive` flags — after a server restart the
 * new runner's ring buffer is empty, so replay alone can't deliver the
 * `message_complete` the client never saw. Not part of the event log;
 * no `_seq`. */
export type RunnerStatusEvent = {
  type: 'runner_status';
  session_id: string;
  is_running: boolean;
};

/** Every frame from the server now carries a monotonic `_seq` so the
 * client can track "what have I already seen" and pass `since_seq` on
 * reconnect to replay only events delivered while it was away. */
export type SeqStamped = { _seq?: number };

export type AgentEvent = (
  | TokenEvent
  | ThinkingEvent
  | UserMessageEvent
  | ToolCallStartEvent
  | ToolCallEndEvent
  | ToolOutputDeltaEvent
  | MessageStartEvent
  | MessageCompleteEvent
  | ErrorEvent
  | RunnerStatusEvent
) &
  SeqStamped;

const TOKEN_STORAGE_KEY = 'bearings:token';

/** Reads the auth token from localStorage. Set via devtools:
 * `localStorage.setItem('bearings:token', 'your-token')`. A full
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

export async function jsonFetch<T>(
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

/** Like `jsonFetch` but for endpoints that return no body (or a body the
 * caller discards). Used for DELETE routes. */
export async function voidFetch(
  fetchImpl: typeof fetch,
  url: string,
  init?: RequestInit
): Promise<void> {
  const res = await fetchImpl(url, withAuth(init));
  if (res.status === 401 && authFailureHandler) authFailureHandler();
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${init?.method ?? 'GET'} ${url} → ${res.status}: ${body}`);
  }
}

export function fetchHealth(fetchImpl: typeof fetch = fetch): Promise<HealthResponse> {
  return jsonFetch<HealthResponse>(fetchImpl, '/api/health');
}

export function openAgentSocket(sessionId: string, sinceSeq = 0): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const token = readAuthToken();
  const params = new URLSearchParams();
  if (token) params.set('token', token);
  // `since_seq=0` is the no-op default (replay whatever's in the
  // buffer). Reconnects pass the last seq the client rendered so the
  // server only replays events newer than that.
  if (sinceSeq > 0) params.set('since_seq', String(sinceSeq));
  const query = params.toString();
  const tail = query ? `?${query}` : '';
  return new WebSocket(
    `${proto}://${window.location.host}/ws/sessions/${sessionId}${tail}`
  );
}
