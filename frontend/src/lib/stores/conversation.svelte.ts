import * as api from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';

import {
  TOOL_OUTPUT_CAP_CHARS,
  applyEvent,
  capToolOutput,
  emptyState,
  hydrateToolCall,
  type ContextUsageState,
  type LiveToolCall,
  type SessionState
} from './conversation/reducer';

// Re-export so existing callers (components, tests) keep importing
// from `$lib/stores/conversation.svelte` without knowing a reducer
// module exists.
export { TOOL_OUTPUT_CAP_CHARS, capToolOutput, type ContextUsageState, type LiveToolCall };

const PAGE_SIZE = 50;

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
  streamingMessageId = $derived<string | null>(this.active()?.streamingMessageId ?? null);
  toolCalls = $derived<LiveToolCall[]>(this.active()?.toolCalls ?? []);
  hasMore = $derived<boolean>(this.active()?.hasMore ?? false);
  pendingApproval = $derived<api.ApprovalRequestEvent | null>(
    this.active()?.pendingApproval ?? null
  );
  contextUsage = $derived<ContextUsageState | null>(this.active()?.contextUsage ?? null);
  todos = $derived<api.TodoItem[] | null>(this.active()?.todos ?? null);

  /** Highest `_seq` rendered for a session; passed to the server on
   * (re)connect as the replay cursor. */
  lastSeqFor(sessionId: string): number {
    return this.states[sessionId]?.lastSeq ?? 0;
  }

  /** Set of message ids the reducer has already finalised for a
   * session. Used by the notification hook to skip replayed
   * `message_complete` frames (the reducer dedups via the same set
   * — we just read it). Returns an empty set for unknown sessions
   * so callers don't need a null check. */
  completedIdsFor(sessionId: string): ReadonlySet<string> {
    return this.states[sessionId]?.completedMessageIds ?? new Set();
  }

  async load(sessionId: string): Promise<api.Session | null> {
    this.sessionId = sessionId;
    const state = this.ensureState(sessionId);
    this.error = null;
    try {
      const [session, page, toolCalls, todos] = await Promise.all([
        api.getSession(sessionId),
        api.listMessagesPage(sessionId, { limit: PAGE_SIZE }),
        api.listToolCalls(sessionId),
        api.getSessionTodos(sessionId)
      ]);
      // Don't wipe in-flight streaming state. We're refreshing the
      // completed-message window from the DB; the ring-buffer replay
      // over the WS will catch us up on anything mid-stream.
      state.messages = page.messages;
      state.hasMore = page.hasMore;
      state.toolCalls = [
        ...toolCalls.map(hydrateToolCall),
        ...state.toolCalls.filter((tc) => !toolCalls.some((row) => row.id === tc.id))
      ];
      state.completedMessageIds = new Set(page.messages.map((m) => m.id));
      // Seed the LiveTodos widget from the server's derived snapshot.
      // Live `todo_write_update` events overwrite this on the next
      // TodoWrite call; until then, the first paint matches whatever
      // the agent's most recent TodoWrite invocation landed. Don't
      // clobber if a replayed WS event already populated todos
      // (race between `load()`'s fetch and a ring-buffer replay) —
      // the WS snapshot is at least as fresh as the REST snapshot.
      if (state.todos === null) {
        state.todos = todos.todos;
      }
      this.totalCost = session.total_cost_usd;
      // Seed the context meter from the cached columns so a fresh
      // load / reconnect has a number to render before the next turn's
      // live `context_usage` event fires. `isAutoCompactEnabled` isn't
      // persisted on the row (it's a per-turn flag), so we default
      // true — the SDK ships with auto-compact on, and a false reading
      // would mis-paint the threshold band more alarmingly than
      // warranted. The next live event overwrites this.
      if (
        session.last_context_pct !== null &&
        session.last_context_tokens !== null &&
        session.last_context_max !== null
      ) {
        state.contextUsage = {
          percentage: session.last_context_pct,
          totalTokens: session.last_context_tokens,
          maxTokens: session.last_context_max,
          isAutoCompactEnabled: true
        };
      }
      // Returned so AgentConnection.connect() can seed its
      // permissionMode from the persisted column without a second
      // getSession round-trip.
      return session;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
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

  /** Clear the pending approval optimistically right after sending
   * the response — waiting for the server's `approval_resolved` event
   * would leave the modal open through the WS round-trip and look
   * unresponsive. If the server rejects the response, the modal will
   * re-appear on the next `approval_request` replay. */
  clearPendingApproval(sessionId: string, requestId: string): void {
    const state = this.states[sessionId];
    if (!state) return;
    if (state.pendingApproval?.request_id !== requestId) return;
    state.pendingApproval = null;
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
    // A fresh user entry is new activity — re-sort to top immediately
    // rather than waiting for MessageStart / MessageComplete. Backend
    // bumps the same column via insert_message; this just beats the
    // next running-poll to the UI.
    sessions.touchSession(sessionId);
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
    applyEvent(state, event, {
      addCost: (sessionId, cost) => {
        if (sessionId === this.sessionId) this.totalCost += cost;
        sessions.bumpCost(sessionId, cost);
      },
      addMessageCount: (sessionId) => sessions.bumpMessageCount(sessionId, 1),
      touchSession: (sessionId) => sessions.touchSession(sessionId),
      setError: (msg) => {
        this.error = msg;
      },
      refreshMessages: (sessionId) => {
        void this.refreshMessages(sessionId);
      }
    });
  }

  /** Replace one message row in-place with a fresh copy from
   * `PATCH /messages/{id}`. Used by the pin / hide-from-context menu
   * handlers so the new flag values paint immediately rather than
   * waiting for the next refreshMessages. No-ops when the session or
   * the message id aren't cached (stale click after navigation). */
  applyMessagePatch(sessionId: string, message: api.Message): void {
    const state = this.states[sessionId];
    if (!state) return;
    const idx = state.messages.findIndex((m) => m.id === message.id);
    if (idx < 0) return;
    state.messages = [
      ...state.messages.slice(0, idx),
      { ...state.messages[idx], ...message },
      ...state.messages.slice(idx + 1)
    ];
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
