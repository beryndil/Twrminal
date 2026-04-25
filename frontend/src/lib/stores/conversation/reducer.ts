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
 *
 * Per-event tail mutation (item 29 / 2026-04-24 refactor): `state.turns`
 * and `state.timeline` are first-class arrays held on `SessionState`
 * and mutated alongside the wire state. Token / thinking / tool-delta
 * events poke fields on the existing tail Turn instead of recomputing
 * the whole array — Svelte 5 $state proxies propagate the field write
 * to subscribers without re-allocating the containing array. Full
 * rebuilds (`rebuildTurnsFromMessages` + `recomputeTimeline`) only run
 * on `load` / `loadOlder` / `refreshMessages` / `setAudits`, which is
 * the prerequisite the 2026-04-21 audit identified for cutting the
 * 1:1 WS-event-to-rebuild ratio.
 */
import type * as api from '$lib/api';

import { buildSettledTurns, buildStreamingTail, type Turn } from '$lib/turns';

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
  /** Server-reported wall-clock since `tool_call_start`, captured from
   * the most recent `tool_progress` keepalive. Null until the first
   * keepalive arrives (or forever, for short calls that finish before
   * TOOL_PROGRESS_INTERVAL_S). Used as a floor for the elapsed readout
   * in `MessageTurn`: a backgrounded tab's `setInterval` is throttled
   * by the browser to ~1/min, so the local `now` clock freezes; the
   * server's monotonic number keeps the readout honest on wake.
   * Mutating this field also nudges Svelte's $state proxy so any
   * derived consumer (tool-call row render) refires. */
  lastProgressMs: number | null;
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
    outputTruncated: capped.truncated,
    lastProgressMs: null
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
  // Most recent context-window snapshot from `context_usage` events.
  // Null until the session has completed one assistant turn. The
  // conversation header reads this to render the context-pressure
  // meter; the session row's cached columns back the first paint
  // after load / reconnect, then live events take over.
  contextUsage: ContextUsageState | null;
  // Live TodoWrite snapshot — drives the sticky LiveTodos widget at
  // the top of the Conversation pane. `null` means the session has
  // never invoked the TodoWrite tool; an empty array means the agent
  // explicitly cleared its list. Full-replacement semantics: every
  // `todo_write_update` event overwrites this field, no per-item
  // merging (TodoWrite itself ships no ids and uses positional
  // identity only).
  todos: api.TodoItem[] | null;
  // True while the initial message-page fetch for this session is in
  // flight (set by `ConversationStore.load`, cleared in its finally).
  // Per-session so concurrent clicks on A then B don't race over a
  // single flag. The Conversation pane reads this to show a centered
  // BearingsMark spinner instead of "No messages yet." when the
  // message list is empty because we haven't loaded yet vs. empty
  // because the session genuinely has no messages.
  loadingInitial: boolean;
  // --- view caches mutated alongside the wire state ----------------
  // `turns` and `timeline` are the canonical view data the
  // Conversation pane subscribes to. The reducer mutates the tail
  // Turn in place during streaming (token / thinking / tool deltas)
  // so per-event work is O(1) instead of O(messages + tool calls).
  // Full rebuilds happen on `load`, `loadOlder`, `refreshMessages`,
  // and `setAudits` — i.e. when the underlying arrays change shape
  // wholesale. See module docstring.
  turns: Turn[];
  audits: api.ReorgAudit[];
  timeline: TimelineItem[];
};

/** Chronologically merged view item — either a turn (user/assistant
 *  exchange) or a reorg audit divider. The Conversation pane renders
 *  this list directly via `{#each timeline as item (item.key)}`; the
 *  reducer keeps it sorted by `when` (ISO timestamp). */
export type TimelineItem =
  | { kind: 'turn'; key: string; when: string; turn: Turn }
  | { kind: 'audit'; key: string; when: string; audit: api.ReorgAudit };

export type ContextUsageState = {
  percentage: number;
  totalTokens: number;
  maxTokens: number;
  isAutoCompactEnabled: boolean;
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
    pendingApproval: null,
    contextUsage: null,
    todos: null,
    // Neutral default: a bare state isn't "loading" until `load()`
    // flips this on. Any code path that instantiates SessionState
    // outside the load flow (WS replay, tests) starts not-loading.
    loadingInitial: false,
    turns: [],
    audits: [],
    timeline: []
  };
}

// --- tail mutation helpers -------------------------------------------
//
// These keep `state.turns` and `state.timeline` in sync with the wire
// state without re-allocating either array on every WS event. Exported
// for the store's `pushUserMessage` / `setAudits` paths and for tests.

/** Locate the in-flight streaming tail by scanning back from the end
 *  of `turns`. Most of the time the tail is the literal last element,
 *  but a mid-stream user prompt (`pushUserMessage` while a previous
 *  reply is still arriving) appends a new user-only turn after the
 *  streaming one — so a strict `turns[length-1]` check would miss it. */
function findStreamingTail(state: SessionState): Turn | null {
  for (let i = state.turns.length - 1; i >= 0; i--) {
    if (state.turns[i].isStreaming) return state.turns[i];
  }
  return null;
}

/** Promote the trailing open user turn to streaming (mirrors
 *  `buildStreamingTail`'s `absorbsLastSettled` branch so the user's
 *  bubble doesn't visually duplicate), or push a fresh streaming tail
 *  when no open user turn is available. Returns the tail Turn for
 *  subsequent in-place writes. */
function ensureStreamingTail(state: SessionState, messageId: string | null): Turn {
  const existing = findStreamingTail(state);
  if (existing) return existing;
  const last = state.turns[state.turns.length - 1];
  if (last && last.user && !last.assistant && !last.isStreaming) {
    last.isStreaming = true;
    last.streamingContent = '';
    last.streamingThinking = '';
    return last;
  }
  const tail: Turn = {
    key: messageId ?? 'streaming:pending',
    user: null,
    assistant: null,
    thinking: '',
    toolCalls: [],
    streamingContent: '',
    streamingThinking: '',
    isStreaming: true
  };
  state.turns.push(tail);
  // `when=''` so `recomputeTimeline`'s sort sinks the streaming tail
  // to the end until `finalizeStreamingTail` fills it in. Audits, the
  // only other items with timestamps later than current settled
  // turns, are appended past it on `setAudits` rebuilds.
  state.timeline.push({
    kind: 'turn',
    key: `turn:${tail.key}`,
    when: '',
    turn: tail
  });
  return tail;
}

/** Close out the streaming tail on `message_complete`: attach the
 *  freshly-persisted assistant message, clear the streaming fringe,
 *  and backfill the timeline `when` if it was an unrooted tail (no
 *  user message). The tail Turn object identity is preserved so the
 *  `{#each}` keyed loop in the Conversation pane doesn't remount the
 *  MessageTurn — the only field that visibly transitions is
 *  `isStreaming` flipping false. */
function finalizeStreamingTail(state: SessionState, msg: api.Message): void {
  const tail = findStreamingTail(state);
  if (!tail) return;
  tail.assistant = msg;
  tail.thinking = msg.thinking ?? '';
  tail.streamingContent = '';
  tail.streamingThinking = '';
  tail.isStreaming = false;
  if (!tail.user) {
    for (const item of state.timeline) {
      if (item.kind === 'turn' && item.turn === tail && item.when === '') {
        item.when = msg.created_at;
        break;
      }
    }
  }
}

/** Append a new user-only turn for an outgoing prompt. Called from
 *  the store's `pushUserMessage`. Audits don't shift mid-stream so
 *  appending to the end of `timeline` is correct: the new turn's
 *  timestamp is "now," which is later than every existing audit. */
export function appendUserTurn(state: SessionState, msg: api.Message): void {
  const turn: Turn = {
    key: msg.id,
    user: msg,
    assistant: null,
    thinking: '',
    toolCalls: [],
    streamingContent: '',
    streamingThinking: '',
    isStreaming: false
  };
  state.turns.push(turn);
  state.timeline.push({
    kind: 'turn',
    key: `turn:${turn.key}`,
    when: msg.created_at,
    turn
  });
}

/** Replace `state.turns` from the current `messages` + `toolCalls` +
 *  streaming fringe. Reuses `buildSettledTurns` (and its WeakMap
 *  cache) so reference-stability for already-settled turns survives
 *  the rebuild. Called on `load`, `loadOlder`, and `refreshMessages`
 *  — the points where the underlying arrays change shape wholesale. */
export function rebuildTurnsFromMessages(state: SessionState): void {
  const settled = buildSettledTurns(state.messages, state.toolCalls);
  let next: Turn[] = settled;
  if (state.streamingActive) {
    const tail = buildStreamingTail(
      settled,
      state.toolCalls,
      state.streamingMessageId,
      state.streamingThinking,
      state.streamingText
    );
    if (tail) {
      next = tail.absorbsLastSettled
        ? [...settled.slice(0, -1), tail.tail]
        : [...settled, tail.tail];
    }
  }
  state.turns.splice(0, state.turns.length, ...next);
}

/** Rebuild `state.timeline` from `state.turns` + `state.audits`,
 *  sorted by ISO timestamp. Called after `rebuildTurnsFromMessages`
 *  and on `setAudits`. Per-event reducer paths (token, thinking,
 *  tool deltas) never call this — the cost we're cutting. */
export function recomputeTimeline(state: SessionState): void {
  const items: TimelineItem[] = [];
  for (const t of state.turns) {
    const when = t.user?.created_at ?? t.assistant?.created_at ?? '';
    items.push({ kind: 'turn', key: `turn:${t.key}`, when, turn: t });
  }
  for (const a of state.audits) {
    items.push({ kind: 'audit', key: `audit:${a.id}`, when: a.created_at, audit: a });
  }
  items.sort((a, b) => {
    if (a.when === b.when) return 0;
    if (a.when === '') return 1;
    if (b.when === '') return -1;
    return a.when < b.when ? -1 : 1;
  });
  state.timeline.splice(0, state.timeline.length, ...items);
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
  /** Re-sort the sidebar so this session floats to the top. Fired on
   * `message_start` so "working" sessions rise immediately rather than
   * waiting for the response to complete. */
  touchSession: (sessionId: string) => void;
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
      // Materialize the streaming tail Turn now so subsequent token /
      // tool events can poke its fields in place. Either promotes the
      // trailing user-only turn (the typical case — user just sent a
      // prompt) or pushes a fresh tail (agentic continuation, no
      // preceding user message in this exchange).
      ensureStreamingTail(state, event.message_id);
      // Agent started work — re-sort the session to the top so "where
      // is it working right now?" is always the topmost row. Runs
      // even for a replay-from-buffer start (no completion recorded
      // yet) because that case means "work the user hasn't seen yet."
      ctx.touchSession(event.session_id);
      return;
    case 'token': {
      // Replay guard: if the start frame's message_id is already
      // completed, ignore mid-turn tokens.
      if (
        state.streamingMessageId &&
        state.completedMessageIds.has(state.streamingMessageId)
      )
        return;
      state.streamingText += event.text;
      // In-place tail mutation — single field write on an existing
      // Turn instead of rebuilding the whole turns array. This is the
      // dominant per-frame cost the 2026-04-21 audit measured.
      const tail = findStreamingTail(state);
      if (tail) tail.streamingContent = state.streamingText;
      return;
    }
    case 'thinking': {
      if (
        state.streamingMessageId &&
        state.completedMessageIds.has(state.streamingMessageId)
      )
        return;
      state.streamingThinking += event.text;
      const tail = findStreamingTail(state);
      if (tail) tail.streamingThinking = state.streamingThinking;
      return;
    }
    case 'tool_call_start': {
      // In-place push rather than array-replace. The file header
      // commits to mutating `state` in place — Svelte 5 `$state`
      // proxies make per-element mutation reactive, and allocating
      // a fresh array per delta was the upstream cause of the
      // 2026-04-21 `buildTurns`/`timeline` re-derivation storm
      // (every event invalidated `toolCalls` → invalidated `turns`
      // → invalidated `timeline`, 227 rebuilds per tool-heavy turn).
      if (state.toolCalls.some((tc) => tc.id === event.tool_call_id)) return;
      const tc: LiveToolCall = {
        id: event.tool_call_id,
        messageId: state.streamingMessageId,
        name: event.name,
        input: event.input,
        output: null,
        error: null,
        ok: null,
        startedAt: Date.now(),
        finishedAt: null,
        outputTruncated: false,
        lastProgressMs: null
      };
      state.toolCalls.push(tc);
      // Attach to the live tail so the MessageTurn's tool-call list
      // grows in place. Re-read the freshly inserted entry from
      // `state.toolCalls` so we share the proxy Svelte 5 $state
      // wrapped on insert — pushing the raw `tc` literal into a
      // second proxied array would yield a separate proxy, and
      // subsequent delta mutations (which look up via
      // `state.toolCalls.find`) would only update one of the two
      // views. This way both pointers share the same reactive
      // proxy and the in-place mutation propagates.
      const inserted = state.toolCalls[state.toolCalls.length - 1];
      const tail = findStreamingTail(state);
      if (tail && inserted.messageId !== null) tail.toolCalls.push(inserted);
      return;
    }
    case 'tool_output_delta': {
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
      // Mutate the matched tool call in place — Svelte 5 $state
      // proxies propagate field writes without re-allocating the
      // containing array, so downstream $derived consumers
      // (`turns`, `timeline`) only refire when the data they
      // actually depend on changes.
      const tc = state.toolCalls.find((c) => c.id === event.tool_call_id);
      if (!tc) return;
      if (tc.finishedAt !== null) return;
      const combined = (tc.output ?? '') + event.delta;
      const capped = capToolOutput(combined);
      tc.output = capped.output;
      if (capped.truncated) tc.outputTruncated = true;
      return;
    }
    case 'tool_progress': {
      // Ephemeral keepalive from the server — our only wire signal
      // while a long sub-agent runs. Two jobs:
      //   1. Floor the elapsed readout: a backgrounded tab's
      //      `setInterval` is throttled hard (≥1 min in most
      //      browsers), so the local `now` clock freezes. Recording
      //      the server's monotonic number as a floor keeps the
      //      readout honest when the tab wakes. `MessageTurn`
      //      reads it via `max(now - startedAt, lastProgressMs)`.
      //   2. Reactivity nudge: mutating a field on the tc fires
      //      Svelte's $state proxy, which refires derived consumers
      //      (the tool-call row) without relying on the local timer.
      // Silently drop if the target call is unknown (replay-after-
      // reconnect corner case) or already finished (a straggler
      // progress tick that races tool_call_end). Matches the
      // `tool_output_delta` guard policy.
      const tc = state.toolCalls.find((c) => c.id === event.tool_call_id);
      if (!tc) return;
      if (tc.finishedAt !== null) return;
      tc.lastProgressMs = event.elapsed_ms;
      return;
    }
    case 'tool_call_end': {
      // The canonical final output arrives here. Apply the cap so
      // a huge final string doesn't bypass the bound that deltas
      // respect. In-place mutation (see `tool_output_delta`).
      const tc = state.toolCalls.find((c) => c.id === event.tool_call_id);
      if (!tc) return;
      const capped =
        event.output !== null
          ? capToolOutput(event.output)
          : { output: null, truncated: false };
      tc.ok = event.ok;
      tc.output = capped.output;
      tc.error = event.error;
      tc.finishedAt = Date.now();
      if (capped.truncated) tc.outputTruncated = true;
      return;
    }
    case 'message_complete': {
      // Dedupe: replay can deliver a complete for a turn that's
      // already in the DB (and hence in `messages`). Clear the
      // streaming fringe either way so the UI returns to idle.
      if (!state.completedMessageIds.has(event.message_id)) {
        const msg: api.Message = {
          id: event.message_id,
          session_id: event.session_id,
          role: 'assistant',
          content: state.streamingText,
          thinking: state.streamingThinking || null,
          created_at: new Date().toISOString()
        };
        state.messages = [...state.messages, msg];
        state.completedMessageIds.add(event.message_id);
        if (event.cost_usd !== null) {
          ctx.addCost(event.session_id, event.cost_usd);
        }
        ctx.addMessageCount(event.session_id);
        // Flip the streaming tail to settled in place — same Turn
        // object reference, so the keyed `{#each}` doesn't remount
        // the MessageTurn. Only `isStreaming` and `assistant` change.
        finalizeStreamingTail(state, msg);
      }
      state.streamingText = '';
      state.streamingThinking = '';
      state.streamingActive = false;
      state.streamingMessageId = null;
      return;
    }
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
    case 'context_usage':
      // Snapshot only — the reducer owns no derived math here. The
      // header component does the color-band lookup from `percentage`
      // at render time so the thresholds live in one place (the
      // component) rather than being split between reducer and view.
      state.contextUsage = {
        percentage: event.percentage,
        totalTokens: event.total_tokens,
        maxTokens: event.max_tokens,
        isAutoCompactEnabled: event.is_auto_compact_enabled
      };
      return;
    case 'todo_write_update':
      // Full replacement — the runner's TodoWriteUpdate carries the
      // whole list every time (matches TodoWrite's own semantics).
      // No per-item merge, no diffing. Replay after reconnect fires
      // the sequence of updates in order so the final state lands
      // correctly even if intermediate snapshots are skipped; we
      // don't dedupe because each fire is a fresh snapshot the view
      // can render safely.
      state.todos = event.todos;
      return;
    case 'runner_status': {
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
        // Clear the dangling tail's streaming flag too — the
        // subsequent `refreshMessages` rebuild will replace `turns`
        // wholesale, but we want the UI to stop showing a streaming
        // spinner immediately rather than waiting for the async
        // refresh to land.
        const tail = findStreamingTail(state);
        if (tail) {
          tail.isStreaming = false;
          tail.streamingContent = '';
          tail.streamingThinking = '';
        }
        ctx.refreshMessages(event.session_id);
      }
      return;
    }
  }
}
