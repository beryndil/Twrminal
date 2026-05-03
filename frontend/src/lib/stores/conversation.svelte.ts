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
import { listMessages, type MessageOut, type MessagePage } from "../api/messages";
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
      return mapAssistantTurn(turns, event.message_id, (turn) => ({
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
          },
        ],
      }));
    case "tool_output_delta":
      return mapToolCall(turns, event.tool_call_id, (call) => {
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
  };
}

export function _resetForTests(): void {
  resetConversation(null);
}
