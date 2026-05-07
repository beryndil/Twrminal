/**
 * Conversation store — per-active-session events + reducer.
 *
 * Per arch §2.2 the canonical conversation store. v0.17.x split this
 * into ``stores/conversation/reducer.ts`` + ``stores/conversation/index.ts``;
 * the rebuild collapses both into one file per arch §2.2 line 405-407
 * ("the reducer is one logical thing; one file").
 *
 * Responsibility:
 *
 * - Hold the per-session message-turn list.
 * - Apply :class:`AgentEvent` deltas via :func:`applyEvent` —
 *   message_start opens an assistant bubble, token streams append to
 *   it, tool_call_start opens a tool drawer row, tool_output_delta
 *   appends to the row's body (truncating at the soft cap), etc.
 * - Track the latest seen ``seq`` so the WebSocket reconnect can
 *   resume via ``?since_seq=<n>``.
 *
 * The reducer is pure: ``(state, event) -> state``. The store's
 * imperative API (``hydrate`` / ``ingestFrame`` / ``reset``) wires the
 * pure reducer to the live store proxy. Components subscribe via
 * Svelte's ``$state`` proxy reads — they never call into the store
 * functions outside of the conversation cluster.
 */
import type { AgentEvent, RunnerStatusEvent } from "../api/events";
import { listMessages, type MessageOut, type MessagePage, type ToolCallOut } from "../api/messages";
import type { StreamFrame } from "../api/streaming";
import { CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS, MESSAGE_PAGE_SIZE, WS_FRAME_KIND_EVENT } from "../config";

/** A single tool-call drawer row inside an assistant turn. */
export interface ToolCallView {
  id: string;
  name: string;
  /** Raw ``tool_input_json`` from the start event, for context-menu copy. */
  inputJson: string;
  /** Output streamed so far (capped at the soft display cap). */
  output: string;
  /** ``output.length`` before truncation — surfaces the elided count. */
  rawLength: number;
  /** ``true`` once a ``tool_call_end`` arrives. */
  done: boolean;
  /** Final ``ok`` flag from ``tool_call_end``; ``null`` while in flight. */
  ok: boolean | null;
  /** Final ``duration_ms`` from ``tool_call_end``; ``null`` while in flight. */
  durationMs: number | null;
  /** Error message attached on a failed ``tool_call_end``. */
  errorMessage: string | null;
  /** Live elapsed-time tick (ms) from ``tool_progress`` keepalives. */
  liveElapsedMs: number;
  /**
   * ``Date.now()`` at the moment the ``tool_call_start`` event was
   * ingested. Used by ``ToolOutput`` to advance the elapsed readout via
   * a local ``setInterval`` clock so the counter ticks every second even
   * when the backend's ``tool_progress`` keepalive only arrives every
   * ``TOOL_PROGRESS_INTERVAL_S`` seconds. ``0`` for calls hydrated from
   * the DB (already ``done``; ``durationMs`` drives the display instead).
   */
  startedAt: number;
}

/**
 * An attachment chip persisted with a sent user message.
 *
 * Populated when the backend threads attachment metadata onto the
 * ``MessageOut`` row or ``user_message`` event. Until that backend
 * wiring lands the field defaults to ``[]`` on every turn — the
 * component is a no-op in that case.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"What a message turn
 * looks like" — attachment chips at the bottom of the user bubble.
 */
export interface SentAttachment {
  /** Stable id for keyed ``{#each}`` rendering. */
  id: string;
  /**
   * Display label shown on the chip (e.g. ``[File 1] foo.log``).
   * Provided by the composer or backend; the component renders it verbatim.
   */
  label: string;
  /** Absolute filesystem path — drives copy-path and open-in-editor actions. */
  path: string;
}

/** A user/assistant turn pair plus its associated tool calls. */
export interface MessageTurnView {
  id: string;
  /** ``"user"`` rows have only the prompt; ``"assistant"`` rows have body + tools. */
  role: "user" | "assistant";
  /** Human-visible body (the user prompt, or the assistant's running reply). */
  body: string;
  /** Optional thinking block (assistant role only). */
  thinking: string;
  /** ``true`` after ``message_complete`` arrives for an assistant turn. */
  complete: boolean;
  /** Tool calls fanned out under this turn, in arrival order. */
  toolCalls: ToolCallView[];
  /** Routing-decision projection from ``RoutingBadge`` / ``MessageOut``. */
  routing: TurnRouting | null;
  /** ``true`` if the agent emitted an ``ErrorEvent`` mid-turn. */
  error: string | null;
  /** Created-at timestamp (server-side; ISO8601). */
  createdAt: string | null;
  /**
   * ``true`` when a ``turn_replayed`` event arrived for this message_id —
   * surfaces as the "↻ resumed" inline annotation on the user bubble
   * (item 1.4). Only ever set on user-role rows.
   */
  resumed: boolean;
  /**
   * SQLite rowid (monotonically increasing per insertion order).
   * Carried from ``MessageOut.seq`` so the reorg picker can identify
   * which messages sit at or after a split boundary without a
   * secondary API call.
   */
  seq: number;
  /**
   * Attachment chips persisted with this user message (gap-cycle-01-015).
   * Empty array for assistant turns and for user turns where no files were
   * staged. Populated by ``rowToTurn`` from ``MessageOut.attachments`` once
   * the backend exposes that field; defaults to ``[]`` in the interim.
   */
  attachments: readonly SentAttachment[];
}

export interface TurnRouting {
  executorModel: string;
  advisorModel: string | null;
  advisorCallsCount: number;
  effortLevel: string;
  routingSource: string;
  routingReason: string;
}

/**
 * A single todo item from the agent's most recent ``TodoWrite`` call.
 * Shape matches the SDK's TodoWrite tool input schema.
 */
/**
 * A single todo item from the agent's most recent ``TodoWrite`` call.
 *
 * ``id`` and ``priority`` are optional — the SDK's built-in TodoWrite
 * tool emits only ``content`` + ``status`` (plus an optional
 * ``activeForm`` annotation); the interface is flexible so both the
 * minimal schema and any richer custom TodoWrite variant work without
 * a parse error.
 */
export interface LiveTodoItem {
  id?: string;
  content: string;
  status: "pending" | "in_progress" | "completed";
  priority?: "high" | "medium" | "low";
  /** Active description emitted by the built-in SDK TodoWrite. */
  activeForm?: string;
}

/**
 * Snapshot of the most recent ``context_usage`` event (item 2.2).
 * ``null`` until the first ``ContextUsage`` frame arrives.
 */
interface ContextUsageSnapshot {
  percentage: number;
  totalTokens: number;
  maxTokens: number;
  model: string | null;
  isAutoCompactEnabled: boolean | null;
  /** Absolute token threshold at which the SDK triggers auto-compact. */
  autoCompactThreshold: number | null;
}

/** Live pending approval request; ``null`` when no modal is shown. */
export interface PendingApproval {
  requestId: string;
  toolName: string;
  toolInputJson: string;
}

interface ConversationState {
  sessionId: string | null;
  turns: MessageTurnView[];
  /** Highest ``seq`` ingested — replay cursor for ``since_seq``. */
  lastSeq: number;
  /** ``true`` while ``hydrate`` is in flight. */
  loading: boolean;
  /** ``true`` while a ``loadOlder()`` fetch is in flight (item 1.3). */
  loadingOlder: boolean;
  /** Last hydrate / WS error. */
  error: Error | null;
  /**
   * Set on ``approval_request``; cleared on ``approval_resolved``
   * (request_id match) or session reset. Drives the approval modals.
   */
  pendingApproval: PendingApproval | null;
  /**
   * ``true`` when the backend reported more messages exist before the
   * current page (item 1.3). Drives the "Load older" affordance.
   */
  hasMore: boolean;
  /**
   * The lowest ``seq`` (SQLite rowid) among the currently loaded
   * turns. Passed as ``before=`` on the next ``loadOlder()`` call.
   * ``null`` when no turns are loaded or pagination is not in use.
   */
  oldestSeq: number | null;
  /**
   * Latest todo list from the agent's most recent ``TodoWrite`` call.
   * Empty array when no ``todo_write_update`` has arrived in this
   * session. Reset to ``[]`` on session-switch so a new session never
   * inherits a previous session's todo state.
   */
  liveTodos: LiveTodoItem[];
  /**
   * ``true`` while the runner is actively streaming a turn. Set by
   * ``message_start``, cleared by ``message_complete`` / ``error``,
   * and reconciled on reconnect via ``runner_status`` (item 1.4).
   * Gating the Stop button on this prevents an indefinite spinner when
   * the runner died while a ``MessageStart`` was open in the buffer.
   */
  streamingActive: boolean;
  /**
   * Assistant ``message_id`` of the live turn, or ``null`` when idle.
   * Carried by the ``runner_status`` event on reconnect; updated on
   * ``message_start`` / ``message_complete``.
   */
  currentTurnId: string | null;
  /**
   * Most recent ``context_usage`` snapshot (item 2.2). ``null`` until
   * the first ``ContextUsage`` frame arrives; reset on session-switch.
   * Drives the ``ContextMeter`` header strip.
   */
  contextUsage: ContextUsageSnapshot | null;
  /**
   * Cache-hit ratio derived from the most recent ``message_complete``
   * frame: ``cache_read_tokens / (executor_input_tokens +
   * cache_read_tokens)``. ``null`` when either token count is absent.
   * Reset on session-switch.
   */
  cacheHitRatio: number | null;
  /**
   * Cumulative executor input tokens for this session, accumulated from
   * every ``message_complete`` frame that carries a non-null
   * ``executor_input_tokens`` value. Reset to ``0`` on session-switch.
   *
   * Drives :component:`TokenMeter` in subscription billing mode
   * (gap-cycle-01-017).
   */
  sessionInputTokens: number;
  /**
   * Cumulative executor output tokens for this session, accumulated
   * from every ``message_complete`` frame that carries a non-null
   * ``executor_output_tokens`` value. Reset to ``0`` on session-switch.
   *
   * Drives :component:`TokenMeter` in subscription billing mode
   * (gap-cycle-01-017).
   */
  sessionOutputTokens: number;
  /**
   * Cumulative cache-read tokens for this session, accumulated from
   * every ``message_complete`` frame that carries a non-null
   * ``cache_read_tokens`` value. Reset to ``0`` on session-switch.
   *
   * Drives :component:`AccentCards` Card 1 — token-cache savings
   * display (gap-cycle-01-019).
   */
  sessionCacheReadTokens: number;
}

const state: ConversationState = $state({
  sessionId: null,
  turns: [],
  lastSeq: 0,
  loading: false,
  loadingOlder: false,
  error: null,
  pendingApproval: null,
  hasMore: false,
  oldestSeq: null,
  liveTodos: [],
  streamingActive: false,
  currentTurnId: null,
  contextUsage: null,
  cacheHitRatio: null,
  sessionInputTokens: 0,
  sessionOutputTokens: 0,
  sessionCacheReadTokens: 0,
});

export const conversationStore = state;

/**
 * Replace the transcript with a freshly-fetched page (oldest first).
 *
 * ``page.has_more`` seeds the "Load older" affordance; ``oldestSeq``
 * is derived from the minimum ``seq`` in the returned items so that
 * the next ``loadOlder()`` call can pass the right ``before=`` cursor.
 */
export function hydrateTurns(sessionId: string, page: MessagePage): void {
  state.sessionId = sessionId;
  state.turns = page.items.map(rowToTurn);
  state.hasMore = page.has_more;
  state.oldestSeq = page.items.length > 0 ? page.items[0].seq : null;
  // Hydrate doesn't reset ``lastSeq`` on its own — the caller resets
  // before subscribing so the cursor matches the just-loaded snapshot.
  state.error = null;
}

/**
 * Merge persisted tool-call rows into the current turns (gap-cycle-03-012).
 *
 * Called after :func:`hydrateTurns` with the result of
 * ``GET /api/sessions/{id}/tool_calls?message_ids=…``. Groups rows by
 * ``message_id`` and attaches them to the matching assistant turns as
 * :interface:`ToolCallView` entries with ``done=true`` so the drawer
 * renders identically to a completed streaming turn.
 *
 * The display cap (:data:`CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS`) is applied
 * here to match the live-streaming path (the ``tool_output_delta``
 * reducer keeps the tail of the last N chars; hydrated output is also
 * tail-trimmed so the elided-count annotation appears correctly).
 *
 * Idempotent: turns whose ``toolCalls`` array is already non-empty are
 * not overwritten — they were populated by WS replay and are up-to-date.
 */
export function hydrateToolCalls(toolCalls: ToolCallOut[]): void {
  if (toolCalls.length === 0) return;
  // Group by message_id for O(n) turn walk.
  const byMessageId = new Map<string, ToolCallOut[]>();
  for (const tc of toolCalls) {
    const list = byMessageId.get(tc.message_id) ?? [];
    list.push(tc);
    byMessageId.set(tc.message_id, list);
  }
  state.turns = state.turns.map((turn) => {
    if (turn.role !== "assistant") return turn;
    // Skip turns that already have tool calls from WS replay.
    if (turn.toolCalls.length > 0) return turn;
    const calls = byMessageId.get(turn.id);
    if (!calls || calls.length === 0) return turn;
    return {
      ...turn,
      toolCalls: calls.map((tc) => {
        const rawLength = tc.output.length;
        const output =
          rawLength > CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS
            ? tc.output.slice(rawLength - CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS)
            : tc.output;
        return {
          id: tc.id,
          name: tc.tool_name,
          inputJson: tc.input_json,
          output,
          rawLength,
          done: true,
          ok: tc.ok,
          durationMs: tc.duration_ms,
          errorMessage: tc.error_message,
          liveElapsedMs: 0,
          startedAt: 0,
        };
      }),
    };
  });
}

/**
 * Seed ``liveTodos`` from the persisted hydration payload returned by
 * ``GET /api/sessions/{id}/todos`` (gap-cycle-03-013).
 *
 * Called once on session open before the WebSocket subscription is
 * established so the ``LiveTodos`` panel renders immediately without
 * waiting for the agent to re-emit a ``todo_write_update`` event.
 * Subsequent ``todo_write_update`` WS events overwrite the seed via
 * :func:`applyTodoState` — the same ``JSON.parse`` path is used in
 * both cases so the behaviour is identical.
 *
 * Malformed JSON (defensive: the server validates the round-trip) is
 * silently ignored — the panel stays hidden rather than crashing.
 */
export function hydrateTodos(todosJson: string): void {
  try {
    state.liveTodos = JSON.parse(todosJson) as LiveTodoItem[];
  } catch {
    // leave liveTodos as-is on parse failure
  }
}

/**
 * Prepend an older page in front of the current turns (item 1.3
 * ``loadOlder()``). Called after a successful ``before=`` fetch;
 * updates ``hasMore`` + ``oldestSeq`` for the next call.
 */
function prependTurns(page: MessagePage): void {
  state.turns = [...page.items.map(rowToTurn), ...state.turns];
  state.hasMore = page.has_more;
  state.oldestSeq = page.items.length > 0 ? page.items[0].seq : null;
}

/** Reset the store; called when the active session changes. */
export function resetConversation(sessionId: string | null): void {
  state.sessionId = sessionId;
  state.turns = [];
  state.lastSeq = 0;
  state.loading = false;
  state.loadingOlder = false;
  state.error = null;
  state.pendingApproval = null;
  state.hasMore = false;
  state.oldestSeq = null;
  state.liveTodos = [];
  state.streamingActive = false;
  state.currentTurnId = null;
  state.contextUsage = null;
  state.cacheHitRatio = null;
  state.sessionInputTokens = 0;
  state.sessionOutputTokens = 0;
  state.sessionCacheReadTokens = 0;
}

/**
 * Load the page of messages that precedes the current view (item 1.3).
 *
 * No-ops when: a fetch is already in flight, there are no older
 * messages (``hasMore`` is false), or no cursor is available.
 * Prepends the result to the current turns array so the UI stays
 * scroll-anchored at the "Load older" button position.
 */
export async function loadOlder(sessionId: string): Promise<void> {
  if (state.loadingOlder || !state.hasMore || state.oldestSeq === null) {
    return;
  }
  state.loadingOlder = true;
  try {
    const page = await listMessages(sessionId, {
      limit: MESSAGE_PAGE_SIZE,
      before: state.oldestSeq,
    });
    // Guard against a session switch arriving while the fetch was in flight.
    if (state.sessionId !== sessionId) return;
    prependTurns(page);
  } catch {
    // loadOlder errors are non-fatal — the user can retry by clicking
    // the affordance again. Don't overwrite the main ``error`` field,
    // which is reserved for the initial hydration failure.
  } finally {
    state.loadingOlder = false;
  }
}

export function setLoading(loading: boolean): void {
  state.loading = loading;
}

export function setError(error: Error | null): void {
  state.error = error;
}

/**
 * Ingest one parsed WebSocket frame. Heartbeat frames are no-ops on
 * the conversation surface (the WS client uses them for liveness;
 * see ``agent.svelte.ts``); event frames flow through the reducer.
 */
export function ingestFrame(frame: StreamFrame): void {
  if (frame.kind !== WS_FRAME_KIND_EVENT) {
    return;
  }
  // runner_status is a synthetic post-replay frame (seq=0, never stored
  // in the ring buffer) — reconcile streamingActive before the seq-dedup
  // filter so it's never dropped.
  if (frame.event.type === "runner_status") {
    applyRunnerStatus(frame.event);
    return;
  }
  if (frame.seq <= state.lastSeq) {
    // Replay tail or reordered duplicate — drop. The runner emits
    // monotonic seq per session so this is safe.
    return;
  }
  // Track streaming state imperatively before the pure turns reducer.
  applyStreamingState(frame.event);
  // Update pendingApproval for out-of-turn approval events BEFORE
  // the pure turns reducer runs (which is a no-op for these events).
  applyApprovalState(frame.event);
  // Update liveTodos for todo_write_update events.
  applyTodoState(frame.event);
  // Update context-usage snapshot and cache-hit ratio (item 2.2).
  applyContextUsage(frame.event);
  applyCacheHit(frame.event);
  applySessionTokens(frame.event);
  state.turns = applyEvent(state.turns, frame.event);
  state.lastSeq = frame.seq;
}

/**
 * Reconcile ``streamingActive`` / ``currentTurnId`` from a
 * ``runner_status`` frame (item 1.4). Called before the seq-dedup
 * filter so the synthetic post-replay frame is never silently dropped.
 */
function applyRunnerStatus(event: RunnerStatusEvent): void {
  state.streamingActive = event.streaming_active;
  state.currentTurnId = event.current_turn_id;
}

/**
 * Imperative reducer arm for streaming-state tracking. Mirrors the
 * runner's own ``is_running`` lifecycle: ``message_start`` opens a
 * live turn; ``message_complete`` and ``error`` close it.
 */
function applyStreamingState(event: AgentEvent): void {
  if (event.type === "message_start") {
    state.streamingActive = true;
    state.currentTurnId = event.message_id;
  } else if (event.type === "message_complete" || event.type === "error") {
    state.streamingActive = false;
    state.currentTurnId = null;
  }
}

/**
 * Imperative reducer arm for approval modal state. Kept separate from
 * :func:`applyEvent` so the pure turns reducer stays testable without
 * side-effectful state writes.
 */
function applyApprovalState(event: AgentEvent): void {
  if (event.type === "approval_request") {
    state.pendingApproval = {
      requestId: event.request_id,
      toolName: event.tool_name,
      toolInputJson: event.tool_input_json,
    };
  } else if (
    event.type === "approval_resolved" &&
    state.pendingApproval?.requestId === event.request_id
  ) {
    state.pendingApproval = null;
  }
}

/**
 * Imperative reducer arm for live todo state. Parses ``todos_json``
 * from a ``todo_write_update`` event and replaces ``liveTodos``.
 * Malformed JSON is silently ignored — the panel retains whatever was
 * last successfully parsed rather than clearing mid-session.
 */
function applyTodoState(event: AgentEvent): void {
  if (event.type !== "todo_write_update") return;
  try {
    state.liveTodos = JSON.parse(event.todos_json) as LiveTodoItem[];
  } catch {
    // leave liveTodos intact on parse failure
  }
}

/**
 * Imperative reducer arm for context-usage state (item 2.2).
 * Overwrites ``contextUsage`` on every ``context_usage`` frame so the
 * ``ContextMeter`` always shows the latest tick.
 */
function applyContextUsage(event: AgentEvent): void {
  if (event.type !== "context_usage") return;
  state.contextUsage = {
    percentage: event.percentage,
    totalTokens: event.total_tokens,
    maxTokens: event.max_tokens,
    model: event.model,
    isAutoCompactEnabled: event.is_auto_compact_enabled,
    autoCompactThreshold: event.auto_compact_threshold,
  };
}

/**
 * Imperative reducer arm for cache-hit ratio (item 2.2).
 *
 * ``cache_hit_ratio = cache_read_tokens / (executor_input_tokens +
 * cache_read_tokens)``. Set ``null`` when either required token count
 * is absent — avoids showing a 0% ratio when the SDK just didn't report
 * cache data (rather than truly having zero cache hits).
 */
function applyCacheHit(event: AgentEvent): void {
  if (event.type !== "message_complete") return;
  const cacheRead = event.cache_read_tokens;
  const execInput = event.executor_input_tokens;
  if (cacheRead === null || execInput === null) {
    state.cacheHitRatio = null;
    return;
  }
  const total = execInput + cacheRead;
  state.cacheHitRatio = total > 0 ? cacheRead / total : 0;
}

/**
 * Accumulate per-session executor token totals from ``message_complete``
 * frames (gap-cycle-01-017).
 *
 * Adds ``executor_input_tokens`` / ``executor_output_tokens`` to the
 * running session totals when both are non-null. Null counts (cache-only
 * turns or pure-tool turns where the SDK omits token data) are skipped so
 * the accumulated total reflects only turns with reliable token data.
 */
function applySessionTokens(event: AgentEvent): void {
  if (event.type !== "message_complete") return;
  const input = event.executor_input_tokens;
  const output = event.executor_output_tokens;
  const cacheRead = event.cache_read_tokens;
  if (input !== null) state.sessionInputTokens += input;
  if (output !== null) state.sessionOutputTokens += output;
  if (cacheRead !== null) state.sessionCacheReadTokens += cacheRead;
}

/**
 * Pure reducer used by :func:`ingestFrame` and the unit tests.
 * Returns a new turns array; never mutates inputs.
 */
export function applyEvent(
  turns: readonly MessageTurnView[],
  event: AgentEvent,
): MessageTurnView[] {
  switch (event.type) {
    case "user_message":
      // Idempotent on replay: hydrate seeds turns from the DB before
      // the WS subscribes, and the WS replays from seq 0 if no
      // ``since_seq`` cursor is sent. Skip the append when a turn
      // with this id already exists.
      if (turns.some((t) => t.id === event.message_id)) return turns as MessageTurnView[];
      return [
        ...turns,
        {
          id: event.message_id,
          role: "user",
          body: event.content,
          thinking: "",
          complete: true,
          toolCalls: [],
          routing: null,
          error: null,
          createdAt: null,
          resumed: false,
          seq: 0,
          attachments: [],
        },
      ];
    case "message_start":
      if (turns.some((t) => t.id === event.message_id)) return turns as MessageTurnView[];
      return [
        ...turns,
        {
          id: event.message_id,
          role: "assistant",
          body: "",
          thinking: "",
          complete: false,
          toolCalls: [],
          routing: null,
          error: null,
          createdAt: null,
          resumed: false,
          seq: 0,
          attachments: [],
        },
      ];
    case "token":
      return mapAssistantTurn(turns, event.message_id, (turn) => ({
        ...turn,
        body: turn.body + event.delta,
      }));
    case "thinking":
      return mapAssistantTurn(turns, event.message_id, (turn) => ({
        ...turn,
        thinking: turn.thinking + event.delta,
      }));
    case "tool_call_start":
      // Idempotent: skip if this tool call already exists in the turn.
      // Prevents duplicate drawer rows when the call was hydrated from
      // the DB (gap-cycle-03-012) and WS replay also sends tool_call_start.
      return mapAssistantTurn(turns, event.message_id, (turn) => {
        if (turn.toolCalls.some((tc) => tc.id === event.tool_call_id)) return turn;
        return {
          ...turn,
          toolCalls: [
            ...turn.toolCalls,
            {
              id: event.tool_call_id,
              name: event.tool_name,
              inputJson: event.tool_input_json,
              output: "",
              rawLength: 0,
              done: false,
              ok: null,
              durationMs: null,
              errorMessage: null,
              liveElapsedMs: 0,
              startedAt: Date.now(),
            },
          ],
        };
      });
    case "tool_output_delta":
      return mapToolCall(turns, event.tool_call_id, (call) => {
        // Skip delta streaming for calls already finalized via DB hydration
        // (gap-cycle-03-012). WS replay sends deltas even for completed calls;
        // skipping prevents re-appending output onto the hydrated full text.
        if (call.done) return call;
        const nextRaw = call.rawLength + event.delta.length;
        const merged = call.output + event.delta;
        const truncated =
          merged.length > CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS
            ? merged.slice(merged.length - CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS)
            : merged;
        return {
          ...call,
          output: truncated,
          rawLength: nextRaw,
        };
      });
    case "tool_call_end":
      return mapToolCall(turns, event.tool_call_id, (call) => ({
        ...call,
        done: true,
        ok: event.ok,
        durationMs: event.duration_ms,
        errorMessage: event.error_message,
      }));
    case "tool_progress":
      return mapToolCall(turns, event.tool_call_id, (call) => ({
        ...call,
        liveElapsedMs: event.elapsed_ms,
      }));
    case "message_complete":
      return mapAssistantTurn(turns, event.message_id, (turn) => ({
        ...turn,
        body: event.content !== "" ? event.content : turn.body,
        complete: true,
      }));
    case "routing_badge":
      return mapAssistantTurn(turns, event.message_id, (turn) => ({
        ...turn,
        routing: {
          executorModel: event.executor_model,
          advisorModel: event.advisor_model,
          advisorCallsCount: event.advisor_calls_count,
          effortLevel: event.effort_level,
          routingSource: event.routing_source,
          routingReason: event.routing_reason,
        },
      }));
    case "error":
      // Attach to the most recent in-flight assistant turn; if there's
      // no live turn (the error fires between turns), append a synthetic
      // assistant turn carrying the error so the user surface still
      // shows it.
      return attachError(turns, event.message);
    case "turn_replayed":
      // Surface as "↻ resumed" inline annotation on the matching user
      // row. Per behavior doc §"Reconnect / resume" the annotation
      // tells the user their queued prompt was re-played to the runner
      // after a restart (not silently re-answered).
      return turns.map((turn) => {
        if (turn.id === event.message_id) {
          return { ...turn, resumed: true };
        }
        return turn;
      });
    case "context_usage":
    case "approval_request":
    case "approval_resolved":
    case "todo_write_update":
    case "runner_status":
      // Out-of-turn / synthetic events are surfaced by other surfaces
      // (inspector, approval modals, streaming reconciliation) — no
      // transcript-level effect. runner_status is handled before this
      // switch in ingestFrame, but the case is listed for exhaustiveness.
      return turns.slice();
    default: {
      // Exhaustiveness guard — TypeScript flags the assignment if a
      // new ``AgentEvent`` variant sneaks in without a case branch.
      const _exhaustive: never = event;
      return _exhaustive;
    }
  }
}

function mapAssistantTurn(
  turns: readonly MessageTurnView[],
  messageId: string,
  fn: (turn: MessageTurnView) => MessageTurnView,
): MessageTurnView[] {
  return turns.map((turn) => {
    if (turn.role === "assistant" && turn.id === messageId) {
      return fn(turn);
    }
    return turn;
  });
}

function mapToolCall(
  turns: readonly MessageTurnView[],
  toolCallId: string,
  fn: (call: ToolCallView) => ToolCallView,
): MessageTurnView[] {
  return turns.map((turn) => {
    if (turn.role !== "assistant") {
      return turn;
    }
    const calls = turn.toolCalls;
    const idx = calls.findIndex((call) => call.id === toolCallId);
    if (idx < 0) {
      return turn;
    }
    const updated = calls.slice();
    updated[idx] = fn(calls[idx]);
    return { ...turn, toolCalls: updated };
  });
}

function attachError(turns: readonly MessageTurnView[], message: string): MessageTurnView[] {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    if (turns[i].role === "assistant" && !turns[i].complete) {
      const next = turns.slice();
      next[i] = { ...turns[i], error: message, complete: true };
      return next;
    }
  }
  return [
    ...turns,
    {
      id: `error-${Date.now()}`,
      role: "assistant",
      body: "",
      thinking: "",
      complete: true,
      toolCalls: [],
      routing: null,
      error: message,
      createdAt: null,
      resumed: false,
      seq: 0,
      attachments: [],
    },
  ];
}

function rowToTurn(row: MessageOut): MessageTurnView {
  return {
    id: row.id,
    role: row.role === "user" ? "user" : "assistant",
    body: row.content,
    thinking: "",
    complete: true,
    toolCalls: [],
    routing:
      row.executor_model !== null
        ? {
            executorModel: row.executor_model,
            advisorModel: row.advisor_model,
            advisorCallsCount: row.advisor_calls_count ?? 0,
            effortLevel: row.effort_level ?? "",
            routingSource: row.routing_source ?? "",
            routingReason: row.routing_reason ?? "",
          }
        : null,
    error: null,
    createdAt: row.created_at,
    resumed: false,
    seq: row.seq,
    // ``MessageOut`` does not yet carry attachment metadata; default to
    // empty array until the backend wiring lands (gap-cycle-01-015).
    attachments: [],
  };
}

export function _resetForTests(): void {
  resetConversation(null);
}
