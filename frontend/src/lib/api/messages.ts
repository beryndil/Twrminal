/**
 * Typed client for ``GET /api/sessions/{id}/messages`` and
 * ``GET /api/messages/{id}`` (item 1.9; ``src/bearings/web/routes/messages.py``).
 *
 * Mirrors :class:`bearings.web.models.messages.MessageOut` /
 * :class:`bearings.web.models.messages.MessagePage` field for field.
 * The conversation pane fetches the tail on session-select and walks
 * backward via ``loadOlder()`` (item 1.3 cursor pagination).
 */
import { messageEndpoint, sessionMessagesEndpoint } from "../config";
import { getJson, type RequestOptions } from "./client";

/**
 * Wire shape for one message row — one-to-one with
 * :class:`bearings.web.models.messages.MessageOut`. Routing/usage
 * fields are nullable across all rows: only assistant rows persisted
 * by item 1.9's ``persist_assistant_turn`` carry real values.
 *
 * ``seq`` is the SQLite rowid — monotonically increasing per insertion
 * order. Pass the lowest ``seq`` in the current view as ``before`` to
 * walk further into the past via ``loadOlder()`` (item 1.3).
 */
export interface MessageOut {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  // Spec §5 routing-decision projection.
  executor_model: string | null;
  advisor_model: string | null;
  effort_level: string | null;
  routing_source: string | null;
  routing_reason: string | null;
  matched_rule_id: number | null;
  // Spec §5 per-model usage projection.
  executor_input_tokens: number | null;
  executor_output_tokens: number | null;
  advisor_input_tokens: number | null;
  advisor_output_tokens: number | null;
  advisor_calls_count: number | null;
  cache_read_tokens: number | null;
  // Legacy flat carriers per spec §5 "Backfill for legacy data".
  input_tokens: number | null;
  output_tokens: number | null;
  // Cursor for backward pagination (item 1.3).
  seq: number;
}

/**
 * Paginated response envelope — mirrors
 * :class:`bearings.web.models.messages.MessagePage`.
 */
export interface MessagePage {
  items: MessageOut[];
  has_more: boolean;
}

interface ListMessagesParams {
  /** Tail-window — return the last N messages. Omit for full transcript. */
  limit?: number;
  /**
   * Backward-pagination cursor (item 1.3). Pass the ``seq`` of the
   * oldest message currently held to fetch the preceding page.
   */
  before?: number;
  signal?: AbortSignal;
}

/**
 * List messages for ``sessionId`` in chronological order (oldest
 * first). Returns a :class:`MessagePage` with ``has_more`` flag.
 * 404 is surfaced via :class:`ApiError`.
 */
export async function listMessages(
  sessionId: string,
  params: ListMessagesParams = {},
): Promise<MessagePage> {
  const options: RequestOptions = {};
  const query: [string, string][] = [];
  if (params.limit !== undefined) {
    query.push(["limit", String(params.limit)]);
  }
  if (params.before !== undefined) {
    query.push(["before", String(params.before)]);
  }
  if (query.length > 0) {
    options.query = query;
  }
  if (params.signal !== undefined) {
    options.signal = params.signal;
  }
  return await getJson<MessagePage>(sessionMessagesEndpoint(sessionId), options);
}

/**
 * Fetch a single message by id. Used by the inspector "Why this
 * model?" panel (item 2.6) — included here so the messages-API
 * client surface in this item's scope mirrors the route module.
 */
export async function getMessage(
  messageId: string,
  options: RequestOptions = {},
): Promise<MessageOut> {
  return await getJson<MessageOut>(messageEndpoint(messageId), options);
}
