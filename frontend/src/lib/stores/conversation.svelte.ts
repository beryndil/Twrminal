import * as api from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';

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
export function capToolOutput(
  next: string
): { output: string; truncated: boolean } {
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

function hydrateToolCall(row: api.ToolCall): LiveToolCall {
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

const PAGE_SIZE = 50;

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
type SessionState = {
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
};

function emptyState(): SessionState {
  return {
    messages: [],
    streamingText: '',
    streamingThinking: '',
    streamingActive: false,
    streamingMessageId: null,
    toolCalls: [],
    hasMore: false,
    lastSeq: 0,
    completedMessageIds: new Set()
  };
}

class ConversationStore {
  sessionId = $state<string | null>(null);
  totalCost = $state(0);
  highlightQuery = $state('');
  loadingOlder = $state(false);
  error = $state<string | null>(null);

  // Per-session state, kept alive across navigation so a session can
  // continue streaming in the background. The active-session getters
  // below pull from this map.
  private states = $state<Record<string, SessionState>>({});

  private ensureState(id: string): SessionState {
    if (!this.states[id]) this.states[id] = emptyState();
    return this.states[id];
  }

  private active(): SessionState | null {
    if (!this.sessionId) return null;
    return this.states[this.sessionId] ?? null;
  }

  // ---- view getters (active session) ------------------------------
  // $derived so components re-render when either the sessionId or the
  // underlying state map changes. Defaults to empty values when no
  // session is selected so templates stay trivial.

  messages = $derived<api.Message[]>(this.active()?.messages ?? []);
  streamingText = $derived<string>(this.active()?.streamingText ?? '');
  streamingThinking = $derived<string>(this.active()?.streamingThinking ?? '');
  streamingActive = $derived<boolean>(this.active()?.streamingActive ?? false);
  streamingMessageId = $derived<string | null>(
    this.active()?.streamingMessageId ?? null
  );
  toolCalls = $derived<LiveToolCall[]>(this.active()?.toolCalls ?? []);
  hasMore = $derived<boolean>(this.active()?.hasMore ?? false);

  /** Highest `_seq` rendered for a session; passed to the server on
   * (re)connect as the replay cursor. */
  lastSeqFor(sessionId: string): number {
    return this.states[sessionId]?.lastSeq ?? 0;
  }

  async load(sessionId: string): Promise<void> {
    this.sessionId = sessionId;
    const state = this.ensureState(sessionId);
    this.error = null;
    try {
      const [session, page, toolCalls] = await Promise.all([
        api.getSession(sessionId),
        api.listMessagesPage(sessionId, { limit: PAGE_SIZE }),
        api.listToolCalls(sessionId)
      ]);
      // Don't wipe in-flight streaming state. We're refreshing the
      // completed-message window from the DB; the ring-buffer replay
      // over the WS will catch us up on anything mid-stream.
      state.messages = page.messages;
      state.hasMore = page.hasMore;
      state.toolCalls = [...toolCalls.map(hydrateToolCall), ...state.toolCalls.filter(tc => !toolCalls.some(row => row.id === tc.id))];
      state.completedMessageIds = new Set(page.messages.map((m) => m.id));
      this.totalCost = session.total_cost_usd;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async loadOlder(): Promise<void> {
    const state = this.active();
    if (!this.sessionId || !state || !state.hasMore || this.loadingOlder) return;
    const first = state.messages[0];
    if (!first) return;
    this.loadingOlder = true;
    try {
      const page = await api.listMessagesPage(this.sessionId, {
        before: first.created_at,
        limit: PAGE_SIZE
      });
      state.messages = [...page.messages, ...state.messages];
      state.hasMore = page.hasMore;
      for (const m of page.messages) state.completedMessageIds.add(m.id);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loadingOlder = false;
    }
  }

  /** Drop the cached state for a session — called when a session is
   * deleted so its in-flight buffer doesn't leak. */
  forget(sessionId: string): void {
    delete this.states[sessionId];
  }

  pushUserMessage(sessionId: string, content: string): void {
    const state = this.ensureState(sessionId);
    state.messages = [
      ...state.messages,
      {
        id: crypto.randomUUID().replaceAll('-', ''),
        session_id: sessionId,
        role: 'user',
        content,
        thinking: null,
        created_at: new Date().toISOString()
      }
    ];
    sessions.bumpMessageCount(sessionId, 1);
    state.streamingText = '';
    state.streamingThinking = '';
    state.streamingActive = true;
    // Sending a new prompt clears a stale "jumped from search" hint.
    this.highlightQuery = '';
  }

  handleEvent(event: api.AgentEvent): void {
    const targetId = event.session_id;
    if (!targetId) return;
    const state = this.ensureState(targetId);
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
            if (targetId === this.sessionId) this.totalCost += event.cost_usd;
            sessions.bumpCost(event.session_id, event.cost_usd);
          }
          sessions.bumpMessageCount(event.session_id, 1);
        }
        state.streamingText = '';
        state.streamingThinking = '';
        state.streamingActive = false;
        state.streamingMessageId = null;
        return;
      case 'error':
        this.error = event.message;
        state.streamingActive = false;
        return;
      case 'user_message':
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
          void this.refreshMessages(targetId);
        }
        return;
    }
  }

  /** Refetch the most recent page of messages for a session without
   * touching streaming state or replacing the active session id. Used
   * to reconcile after `runner_status` reports drift. */
  private async refreshMessages(sessionId: string): Promise<void> {
    const state = this.ensureState(sessionId);
    try {
      const page = await api.listMessagesPage(sessionId, { limit: PAGE_SIZE });
      state.messages = page.messages;
      state.hasMore = page.hasMore;
      state.completedMessageIds = new Set(page.messages.map((m) => m.id));
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }
}

export const conversation = new ConversationStore();
