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
import type { AgentEvent } from "../api/events";
import type { MessageOut } from "../api/messages";
import type { StreamFrame } from "../api/streaming";
import { CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS, WS_FRAME_KIND_EVENT } from "../config";

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
}

export interface TurnRouting {
  executorModel: string;
  advisorModel: string | null;
  advisorCallsCount: number;
  effortLevel: string;
  routingSource: string;
  routingReason: string;
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
  /** Last hydrate / WS error. */
  error: Error | null;
  /**
   * Set on ``approval_request``; cleared on ``approval_resolved``
   * (request_id match) or session reset. Drives the approval modals.
   */
  pendingApproval: PendingApproval | null;
}

const state: ConversationState = $state({
  sessionId: null,
  turns: [],
  lastSeq: 0,
  loading: false,
  error: null,
  pendingApproval: null,
});

export const conversationStore = state;

/** Replace the transcript with a freshly-fetched history (oldest first). */
export function hydrateTurns(sessionId: string, rows: readonly MessageOut[]): void {
  state.sessionId = sessionId;
  state.turns = rows.map(rowToTurn);
  // Hydrate doesn't reset ``lastSeq`` on its own — the caller resets
  // before subscribing so the cursor matches the just-loaded snapshot.
  state.error = null;
}

/** Reset the store; called when the active session changes. */
export function resetConversation(sessionId: string | null): void {
  state.sessionId = sessionId;
  state.turns = [];
  state.lastSeq = 0;
  state.loading = false;
  state.error = null;
  state.pendingApproval = null;
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
  if (frame.seq <= state.lastSeq) {
    // Replay tail or reordered duplicate — drop. The runner emits
    // monotonic seq per session so this is safe.
    return;
  }
  // Update pendingApproval for out-of-turn approval events BEFORE
  // the pure turns reducer runs (which is a no-op for these events).
  applyApprovalState(frame.event);
  state.turns = applyEvent(state.turns, frame.event);
  state.lastSeq = frame.seq;
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
    case "context_usage":
    case "turn_replayed":
    case "approval_request":
    case "approval_resolved":
    case "todo_write_update":
      // Out-of-turn events are surfaced by other inspector / approval
      // surfaces — no transcript-level effect.
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
  };
}

export function _resetForTests(): void {
  resetConversation(null);
}
