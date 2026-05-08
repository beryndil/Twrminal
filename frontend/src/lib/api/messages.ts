/**
 * Typed client for ``GET /api/sessions/{id}/messages`` and
 * ``GET /api/messages/{id}`` (item 1.9; ``src/bearings/web/routes/messages.py``).
 *
 * Mirrors :class:`bearings.web.models.messages.MessageOut` /
 * :class:`bearings.web.models.messages.MessagePage` field for field.
 * The conversation pane fetches the tail on session-select and walks
 * backward via ``loadOlder()`` (item 1.3 cursor pagination).
 */
import {
  messageDeleteEndpoint,
  messageEndpoint,
  messageHiddenEndpoint,
  messageMoveEndpoint,
  messagePinnedEndpoint,
  sessionMessagesEndpoint,
  sessionToolCallsEndpoint,
} from "../config";
import { deleteResource, getJson, patchJson, postJson, type RequestOptions } from "./client";

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
  /** Ordered rule ids tested by the routing engine (``RoutingDecision.evaluated_rules``).
   *  Empty array for manual/legacy rows or rows predating this column. */
  evaluated_rules: number[];
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
  // G3 context-menu state columns.
  pinned: boolean;
  hidden_from_context: boolean;
}

/**
 * Paginated response envelope — mirrors
 * :class:`bearings.web.models.messages.MessagePage`.
 */
export interface MessagePage {
  items: MessageOut[];
  has_more: boolean;
}

/**
 * One persisted tool-call row — mirrors
 * :class:`bearings.web.models.sessions.ToolCallOut` (gap-cycle-03-012).
 *
 * Used by :func:`listToolCalls` to hydrate tool-work drawer rows on
 * assistant turns when the ring buffer no longer holds the original
 * streaming events.
 */
export interface ToolCallOut {
  id: string;
  session_id: string;
  message_id: string;
  tool_name: string;
  input_json: string;
  output: string;
  ok: boolean | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
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

/**
 * Pin or unpin a message bubble via ``PATCH /api/messages/{id}/pinned`` (G3).
 * ``pinned=true`` floats the bubble in the conversation header.
 */
export async function patchMessagePinned(
  messageId: string,
  pinned: boolean,
  options: RequestOptions = {},
): Promise<MessageOut> {
  return await patchJson<MessageOut>(messagePinnedEndpoint(messageId), { pinned }, options);
}

/**
 * Show or hide a message from the context window via
 * ``PATCH /api/messages/{id}/hidden`` (G3).
 * ``hidden=true`` drops it from the next prompt context.
 */
export async function patchMessageHidden(
  messageId: string,
  hidden: boolean,
  options: RequestOptions = {},
): Promise<MessageOut> {
  return await patchJson<MessageOut>(messageHiddenEndpoint(messageId), { hidden }, options);
}

/**
 * Delete a message via ``DELETE /api/messages/{id}`` (G3).
 * Returns 204 No Content — no body.
 */
export async function deleteMessage(
  messageId: string,
  options: RequestOptions = {},
): Promise<void> {
  return await deleteResource<void>(messageDeleteEndpoint(messageId), options);
}

/**
 * Re-parent a message to another session via
 * ``POST /api/messages/{id}/move`` (G3).
 * Returns the updated message row.
 */
export async function moveMessage(
  messageId: string,
  targetSessionId: string,
  options: RequestOptions = {},
): Promise<MessageOut> {
  return await postJson<MessageOut>(
    messageMoveEndpoint(messageId),
    { target_session_id: targetSessionId },
    options,
  );
}

/**
 * Fetch persisted tool-call rows for the listed assistant message ids
 * via ``GET /api/sessions/{id}/tool_calls?message_ids=…`` (gap-cycle-03-012).
 *
 * Called alongside :func:`listMessages` on session-open so that
 * tool-work drawer rows are visible on assistant turns whose streaming
 * events are no longer in the ring buffer.
 *
 * @param sessionId - The session to query.
 * @param messageIds - Assistant message ids from the current page. Pass
 *   an empty array to skip the request (no-op — returns ``[]``).
 * @param options - Optional request overrides (signal, etc.).
 */
export async function listToolCalls(
  sessionId: string,
  messageIds: readonly string[],
  options: RequestOptions = {},
): Promise<ToolCallOut[]> {
  if (messageIds.length === 0) {
    return [];
  }
  const query: [string, string][] = messageIds.map((id) => ["message_ids", id]);
  return await getJson<ToolCallOut[]>(sessionToolCallsEndpoint(sessionId), {
    ...options,
    query,
  });
}
