/**
 * Typed client for ``GET /api/sessions``.
 *
 * Mirrors the response shape declared by
 * :class:`bearings.web.models.sessions.SessionOut`. Per arch §1.2 the
 * client is one file per backend route group, so this module owns the
 * ``sessions`` surface; ``tags.ts`` owns the ``tags`` surface, etc.
 *
 * The query shape for tag filtering is repeated ``tag_ids`` per
 * ``docs/behavior/chat.md`` §"creates a chat" + master item #537's
 * "OR semantics across tags" — a session matching ANY of the listed
 * tags is included. The backend route is
 * :func:`bearings.web.routes.sessions.list_sessions`; this client's
 * job is to project the ``Iterable<number>`` of selected tag ids onto
 * the wire shape.
 */
import { API_SESSIONS_ENDPOINT } from "../config";
import { getJson, postJson, type RequestOptions } from "./client";

/**
 * Wire shape for one session row — one-to-one with
 * :class:`bearings.web.models.sessions.SessionOut`. The fields the
 * sidebar actually reads are ``id``, ``kind``, ``title``, ``pinned``,
 * ``error_pending``, ``closed_at``, ``checklist_item_id``,
 * ``updated_at``. The remainder is round-tripped so a future
 * inspector / conversation-header consumer doesn't have to broaden
 * the type.
 */
export interface SessionOut {
  id: string;
  kind: string;
  title: string;
  description: string | null;
  session_instructions: string | null;
  working_dir: string;
  model: string;
  permission_mode: string | null;
  max_budget_usd: number | null;
  total_cost_usd: number;
  message_count: number;
  last_context_pct: number | null;
  last_context_tokens: number | null;
  last_context_max: number | null;
  pinned: boolean;
  error_pending: boolean;
  checklist_item_id: number | null;
  created_at: string;
  updated_at: string;
  last_viewed_at: string | null;
  last_completed_at: string | null;
  closed_at: string | null;
  /**
   * Agent-authored 1-3 sentence summary of why the session was
   * closed, written by the ``close_session`` MCP tool when the agent
   * judges the user's task complete. Surfaced as the sidebar tooltip
   * on closed rows; ``null`` for rows closed manually (or never).
   */
  closing_summary: string | null;
}

interface ListSessionsParams {
  /** ``"chat"`` / ``"checklist"`` — narrows the result by ``sessions.kind``. */
  kind?: string;
  /** ``false`` excludes rows whose ``closed_at`` is set. */
  includeClosed?: boolean;
  /**
   * OR-semantics filter — sessions attached to **at least one** of
   * the listed ids appear. An empty iterable applies no filter (the
   * client treats "no selection" the same as "no parameter"); pass
   * ``undefined`` to make the omission explicit.
   */
  tagIds?: Iterable<number>;
  signal?: AbortSignal;
}

/**
 * Fetch the session list with the requested filters applied.
 *
 * @throws :class:`ApiError` on non-2xx responses (422 for an unknown
 *   ``kind``, 5xx for backend faults).
 */
/**
 * Reopen a closed session via ``POST /api/sessions/{id}/reopen``. The
 * server clears ``closed_at`` while preserving any ``closing_summary``
 * (per ``docs/behavior/paired-chats.md`` §"Reopen semantics" — the
 * agent-authored summary stays available as session metadata so the
 * operator can see what the agent thought it had finished). Returns
 * the refreshed session row.
 */
export async function reopenSession(
  sessionId: string,
  options: RequestOptions = {},
): Promise<SessionOut> {
  const path = `${API_SESSIONS_ENDPOINT}/${encodeURIComponent(sessionId)}/reopen`;
  return await postJson<SessionOut>(path, null, options);
}

/**
 * Wire shape for ``POST /api/sessions`` — one-to-one with
 * :class:`bearings.web.models.sessions.SessionCreate`. ``tag_ids``
 * defaults to an empty list at the API boundary; the new-session form
 * enforces the "≥1 tag" rule at the UI layer.
 *
 * Not exported: the only consumer today is :func:`createSession`'s
 * argument list. A second consumer would re-export from here; until
 * that lands, knip flags an exported-but-unused declaration.
 */
interface SessionCreateBody {
  kind: string;
  title: string;
  working_dir: string;
  model: string;
  description?: string | null;
  session_instructions?: string | null;
  permission_mode?: string | null;
  max_budget_usd?: number | null;
  tag_ids?: number[];
}

/**
 * Create a session via ``POST /api/sessions``. The server returns 201
 * with the freshly-created :class:`SessionOut` row and a ``Location``
 * header pointing at ``/api/sessions/<id>``. Caller follows up with
 * :func:`sendPrompt` if it has a first-message payload (the create
 * endpoint itself only inserts the row; queueing the first user turn
 * is a separate step so the create flow can succeed even when the
 * runner-factory is offline).
 */
export async function createSession(
  body: SessionCreateBody,
  options: RequestOptions = {},
): Promise<SessionOut> {
  return await postJson<SessionOut>(API_SESSIONS_ENDPOINT, body, options);
}

export async function listSessions(params: ListSessionsParams = {}): Promise<SessionOut[]> {
  const query: Array<readonly [string, string]> = [];
  if (params.kind !== undefined) {
    query.push(["kind", params.kind]);
  }
  if (params.includeClosed !== undefined) {
    query.push(["include_closed", params.includeClosed ? "true" : "false"]);
  }
  if (params.tagIds !== undefined) {
    for (const id of params.tagIds) {
      query.push(["tag_ids", String(id)]);
    }
  }
  const options: RequestOptions = {};
  if (query.length > 0) {
    options.query = query;
  }
  if (params.signal !== undefined) {
    options.signal = params.signal;
  }
  return await getJson<SessionOut[]>(API_SESSIONS_ENDPOINT, options);
}
