/**
 * Pure event reducer for per-session conversation state.
 *
 * Split out of `conversation.svelte.ts` so the class stays focused on
 * state + derived getters + load/persist, while the per-event logic
 * (and its invariants: replay-safe deduping, memory-cap on tool
 * output, streaming-fringe ownership) lives where it can be read and
 * tested without wading through the view bindings.
 *
 * The reducer mutates `state` in place — Svelte 5's `$state`
 * proxies make in-place mutation reactive, so returning a new object
 * would only add allocations without helping reactivity. External
 * side effects (session-row cost bump, running total update, error
 * surface, post-drift message refresh) travel through `ctx` so this
 * module stays free of store / API dependencies.
 */
import type * as api from '$lib/api';

export type LiveToolCall = {
  id: string;
  messageId: string | null;
  name: string;
  input: Record<string, unknown>;
  output: string | null;
  error: string | null;
  ok: boolean | null; // null until tool_call_end arrives
  startedAt: number;
  finishedAt: number | null;
  /** True when the output has been head-truncated by the reducer to
   * stay under TOOL_OUTPUT_CAP_CHARS. UI-only; not round-tripped to
   * DB. Set once and stays set for the lifetime of the tc. */
  outputTruncated: boolean;
};

/** Hard cap on a single tool call's `output` string length held in
 * the browser store. A runaway tool emitting 500MB would otherwise
 * balloon this one field unbounded. Terminal-semantics: when we
 * overflow, we keep the *tail* (most recent output) and drop the
 * head, prefixed with a truncation marker. 5M chars ≈ 5MB of ASCII,
 * more for multibyte — still well under what a browser tab handles
 * comfortably. */
export const TOOL_OUTPUT_CAP_CHARS = 5_000_000;

/** Applied on every growth of `tc.output` (streamed delta or
 * hydration of a huge persisted row). Returns the possibly-truncated
 * string and whether truncation occurred on this call. */
export function capToolOutput(next: string): { output: string; truncated: boolean } {
  if (next.length <= TOOL_OUTPUT_CAP_CHARS) {
    return { output: next, truncated: false };
  }
  const dropped = next.length - TOOL_OUTPUT_CAP_CHARS;
  const marker = `…[truncated ${dropped.toLocaleString()} chars]…\n`;
  return {
    output: marker + next.slice(-TOOL_OUTPUT_CAP_CHARS),
    truncated: true
  };
}

export function hydrateToolCall(row: api.ToolCall): LiveToolCall {
  let parsedInput: Record<string, unknown> = {};
  try {
    parsedInput = JSON.parse(row.input) as Record<string, unknown>;
  } catch {
    // Malformed JSON — show as empty rather than crash the panel.
  }
  const startedAt = new Date(row.started_at).getTime();
  const finishedAt = row.finished_at ? new Date(row.finished_at).getTime() : null;
  const ok = finishedAt === null ? null : row.error === null;
  // Persisted output can itself exceed the cap if a completed tool
  // emitted a huge final string — apply the same head-truncation so
  // the store never holds more than the cap per tc.
  const capped =
    row.output !== null ? capToolOutput(row.output) : { output: null, truncated: false };
  return {
    id: row.id,
    messageId: row.message_id,
    name: row.name,
    input: parsedInput,
    output: capped.output,
    error: row.error,
    ok,
    startedAt,
    finishedAt,
    outputTruncated: capped.truncated
  };
}

/**
 * Per-session streaming state. Kept in a cache keyed by session id so
 * navigating to another session doesn't throw away an in-flight
 * stream's partial text/thinking/tool calls. When the user switches
 * back, the existing entry is reused and the only thing that changes
 * is which entry the view bindings look at.
 *
 * `lastSeq` is the highest `_seq` this client has rendered for this
 * session; it's passed to the server as `since_seq` on reconnect so
 * the server replays only what arrived while we were away.
 */
export type SessionState = {
  messages: api.Message[];
  streamingText: string;
  streamingThinking: string;
  streamingActive: boolean;
  streamingMessageId: string | null;
  toolCalls: LiveToolCall[];
  hasMore: boolean;
  lastSeq: number;
  // Message ids we've already pushed into `messages`. Replay after a
  // reconnect can deliver a duplicate `message_complete` for a turn
  // that finished in the DB while we were away; dedupe on push.
  completedMessageIds: Set<string>;
  // Outstanding tool-use approval prompt. Non-null means the agent
  // is blocked waiting for the user to click Approve / Deny in the
  // modal. Cleared by a matching `approval_resolved` event (any tab),
  // or optimistically by the agent connection right after sending the
  // response. Reconnect replays the `approval_request` from the ring
  // buffer so the modal reappears if the tab was closed mid-prompt.
  pendingApproval: api.ApprovalRequestEvent | null;
};

export function emptyState(): SessionState {
  return {
    messages: [],
    streamingText: '',
    streamingThinking: '',
    streamingActive: false,
    streamingMessageId: null,
    toolCalls: [],
    hasMore: false,
    lastSeq: 0,
    completedMessageIds: new Set(),
    pendingApproval: null
  };
}

/**
 * Side-effect surface the reducer needs. Kept small and injected so
 * the reducer has no import edge on `sessions`, `api`, or the store
 * itself — everything impure goes through here.
 */
export type ReducerCtx = {
  /** Message-complete cost arrived: the implementation owns both
   * bumping the active-session running total (when this session is
   * the one rendered) and the sidebar row's badge. */
  addCost: (sessionId: string, cost: number) => void;
  /** A message was persisted (user push or message_complete): bump the
   * sidebar row's msg-count badge. */
  addMessageCount: (sessionId: string) => void;
  /** Surface an error to the user. */
  setError: (msg: string) => void;
  /** `runner_status` said the server is idle but we had streaming
   * state. Reconcile by refreshing the message window from DB. Async
   * but fire-and-forget — the UI clears the fringe synchronously. */
  refreshMessages: (sessionId: string) => void;
};

export function applyEvent(
  state: SessionState,
  event: api.AgentEvent,
  ctx: ReducerCtx
): void {
  // Advance the replay cursor before any early-returns below so a
  // malformed event type still marks itself seen.
  if (typeof event._seq === 'number' && event._seq > state.lastSeq) {
    state.lastSeq = event._seq;
  }
  switch (event.type) {
    case 'message_start':
      // A replay after reconnect might re-deliver a start frame for
      // a message that already completed and sits in `messages`.
      // Skip it so the streaming row doesn't light up for a done
      // turn.
      if (state.completedMessageIds.has(event.message_id)) return;
      state.streamingMessageId = event.message_id;
      state.streamingActive = true;
      return;
    case 'token':
      // Replay guard: if the start frame's message_id is already
      // completed, ignore mid-turn tokens.
      if (
        state.streamingMessageId &&
        state.completedMessageIds.has(state.streamingMessageId)
      )
        return;
      state.streamingText += event.text;
      return;
    case 'thinking':
      if (
        state.streamingMessageId &&
        state.completedMessageIds.has(state.streamingMessageId)
      )
        return;
      state.streamingThinking += event.text;
      return;
    case 'tool_call_start':
      if (state.toolCalls.some((tc) => tc.id === event.tool_call_id)) return;
      state.toolCalls = [
        ...state.toolCalls,
        {
          id: event.tool_call_id,
          messageId: state.streamingMessageId,
          name: event.name,
          input: event.input,
          output: null,
          error: null,
          ok: null,
          startedAt: Date.now(),
          finishedAt: null,
          outputTruncated: false
        }
      ];
      return;
    case 'tool_output_delta':
      // Four invariants, all enforced here:
      //   1. Ordering — drop if the target call already finished.
      //      The ring buffer's `_seq` already orders events, but a
      //      replay after reconnect can deliver a late delta that
      //      predates `tool_call_end` we already rendered.
      //   2. Append — delta grows `output` in-place.
      //   3. Memory cap — head-truncate to TOOL_OUTPUT_CAP_CHARS.
      //   4. Persistence — backend does idempotent DB append per
      //      delta, so a reconnecting client pulls cumulative
      //      output from history, not from the missed live frames.
      state.toolCalls = state.toolCalls.map((tc) => {
        if (tc.id !== event.tool_call_id) return tc;
        if (tc.finishedAt !== null) return tc;
        const combined = (tc.output ?? '') + event.delta;
        const capped = capToolOutput(combined);
        return {
          ...tc,
          output: capped.output,
          outputTruncated: tc.outputTruncated || capped.truncated
        };
      });
      return;
    case 'tool_call_end': {
      // The canonical final output arrives here. Apply the cap so
      // a huge final string doesn't bypass the bound that deltas
      // respect.
      const capped =
        event.output !== null
          ? capToolOutput(event.output)
          : { output: null, truncated: false };
      state.toolCalls = state.toolCalls.map((tc) =>
        tc.id === event.tool_call_id
          ? {
              ...tc,
              ok: event.ok,
              output: capped.output,
              error: event.error,
              finishedAt: Date.now(),
              outputTruncated: tc.outputTruncated || capped.truncated
            }
          : tc
      );
      return;
    }
    case 'message_complete':
      // Dedupe: replay can deliver a complete for a turn that's
      // already in the DB (and hence in `messages`). Clear the
      // streaming fringe either way so the UI returns to idle.
      if (!state.completedMessageIds.has(event.message_id)) {
        state.messages = [
          ...state.messages,
          {
            id: event.message_id,
            session_id: event.session_id,
            role: 'assistant',
            content: state.streamingText,
            thinking: state.streamingThinking || null,
            created_at: new Date().toISOString()
          }
        ];
        state.completedMessageIds.add(event.message_id);
        if (event.cost_usd !== null) {
          ctx.addCost(event.session_id, event.cost_usd);
        }
        ctx.addMessageCount(event.session_id);
      }
      state.streamingText = '';
      state.streamingThinking = '';
      state.streamingActive = false;
      state.streamingMessageId = null;
      return;
    case 'error':
      ctx.setError(event.message);
      state.streamingActive = false;
      return;
    case 'user_message':
      return;
    case 'approval_request':
      // If an older (already-resolved or stale) request replays on
      // reconnect, don't overwrite a newer pending one. `_seq`
      // ordering guarantees the newest-by-seq request wins.
      state.pendingApproval = {
        type: 'approval_request',
        session_id: event.session_id,
        request_id: event.request_id,
        tool_name: event.tool_name,
        input: event.input,
        tool_use_id: event.tool_use_id
      };
      return;
    case 'approval_resolved':
      if (state.pendingApproval?.request_id === event.request_id) {
        state.pendingApproval = null;
      }
      return;
    case 'runner_status':
      // Sent once right after replay on every (re)connect. If the
      // server says no turn is in-flight but we think one is, the
      // most likely cause is a server restart that killed the SDK
      // mid-stream: the shutdown path persisted the partial, but we
      // never received `message_complete`. Drop the streaming fringe
      // and refresh from DB so the persisted partial shows up.
      if (!event.is_running && state.streamingActive) {
        state.streamingText = '';
        state.streamingThinking = '';
        state.streamingActive = false;
        state.streamingMessageId = null;
        ctx.refreshMessages(event.session_id);
      }
      return;
  }
}
