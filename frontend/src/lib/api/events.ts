/**
 * TypeScript mirror of :class:`bearings.agent.events.AgentEvent` —
 * the discriminated union the per-session WebSocket fans out.
 *
 * The wire shapes are pinned by ``src/bearings/agent/events.py`` (item
 * 1.1). Each interface here lines up with one Pydantic model 1:1.
 * Keeping the field names identical to the backend lets the frontend
 * reducer dispatch on ``event.type`` without an adapter layer.
 *
 * The backend uses ``Optional[int]`` for usage columns to carry
 * ``unknown_legacy`` rows from spec §5; that surface maps to
 * ``number | null`` here. New fields on the backend MUST be reflected
 * here in the same commit, since the conversation reducer's
 * exhaustive-switch on ``event.type`` will otherwise lose coverage
 * silently.
 */

interface BaseEvent {
  session_id: string;
}

export interface UserMessageEvent extends BaseEvent {
  type: "user_message";
  message_id: string;
  content: string;
}

export interface TokenEvent extends BaseEvent {
  type: "token";
  message_id: string;
  delta: string;
}

export interface ThinkingEvent extends BaseEvent {
  type: "thinking";
  message_id: string;
  delta: string;
}

export interface ToolCallStartEvent extends BaseEvent {
  type: "tool_call_start";
  message_id: string;
  tool_call_id: string;
  tool_name: string;
  tool_input_json: string;
}

export interface ToolOutputDeltaEvent extends BaseEvent {
  type: "tool_output_delta";
  tool_call_id: string;
  delta: string;
}

export interface ToolCallEndEvent extends BaseEvent {
  type: "tool_call_end";
  message_id: string;
  tool_call_id: string;
  ok: boolean;
  duration_ms: number;
  output_summary: string;
  error_message: string | null;
}

export interface ToolProgressEvent extends BaseEvent {
  type: "tool_progress";
  tool_call_id: string;
  elapsed_ms: number;
}

export interface MessageStartEvent extends BaseEvent {
  type: "message_start";
  message_id: string;
}

export interface MessageCompleteEvent extends BaseEvent {
  type: "message_complete";
  message_id: string;
  content: string;
  executor_input_tokens: number | null;
  executor_output_tokens: number | null;
  advisor_input_tokens: number | null;
  advisor_output_tokens: number | null;
  advisor_calls_count: number;
  cache_read_tokens: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface RoutingBadgeEvent extends BaseEvent {
  type: "routing_badge";
  message_id: string;
  executor_model: string;
  advisor_model: string | null;
  advisor_calls_count: number;
  effort_level: string;
  routing_source: string;
  routing_reason: string;
}

export interface ContextUsageEvent extends BaseEvent {
  type: "context_usage";
  percentage: number;
  total_tokens: number;
  max_tokens: number;
  /** Model name the context is calculated for (null on older SDK builds). */
  model: string | null;
  /** Whether auto-compact is enabled for this session. */
  is_auto_compact_enabled: boolean | null;
  /**
   * Absolute token threshold at which auto-compact triggers.
   * Present only when ``is_auto_compact_enabled`` is true and the SDK
   * version exposes the field.
   */
  auto_compact_threshold: number | null;
}

export interface ErrorEvent extends BaseEvent {
  type: "error";
  message: string;
  fatal: boolean;
}

export interface TurnReplayedEvent extends BaseEvent {
  type: "turn_replayed";
  message_id: string;
}

/**
 * Turn-interrupted marker — emitted by the backend when the turn ended
 * because the user pressed Stop.  Arrives after ``message_complete``
 * (or in its absence when the SDK produced no body before interrupt).
 *
 * Per ``docs/behavior/chat.md`` §"Stopping or interrupting a turn":
 * the partially-streamed assistant bubble gains a ``[stopped]``
 * annotation.
 */
export interface TurnStoppedEvent extends BaseEvent {
  type: "turn_stopped";
  message_id: string;
}

export interface ApprovalRequestEvent extends BaseEvent {
  type: "approval_request";
  request_id: string;
  tool_name: string;
  tool_input_json: string;
}

export interface ApprovalResolvedEvent extends BaseEvent {
  type: "approval_resolved";
  request_id: string;
  approved: boolean;
}

export interface TodoWriteUpdateEvent extends BaseEvent {
  type: "todo_write_update";
  todos_json: string;
}

/**
 * Post-replay status frame — sent once on WS connect after the replay drain.
 * The client uses ``streaming_active`` to reconcile its spinner state; seq=0
 * is intentional (synthetic frame, not stored in the ring buffer) and is
 * handled before the seq-dedup filter in :func:`ingestFrame`.
 */
export interface RunnerStatusEvent extends BaseEvent {
  type: "runner_status";
  streaming_active: boolean;
  current_turn_id: string | null;
}

export type AgentEvent =
  | UserMessageEvent
  | TokenEvent
  | ThinkingEvent
  | ToolCallStartEvent
  | ToolOutputDeltaEvent
  | ToolCallEndEvent
  | ToolProgressEvent
  | MessageStartEvent
  | MessageCompleteEvent
  | RoutingBadgeEvent
  | ContextUsageEvent
  | ErrorEvent
  | TurnReplayedEvent
  | TurnStoppedEvent
  | ApprovalRequestEvent
  | ApprovalResolvedEvent
  | TodoWriteUpdateEvent
  | RunnerStatusEvent;
