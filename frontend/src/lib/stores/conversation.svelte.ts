import * as api from '$lib/api';
import { sessions } from '$lib/stores/sessions.svelte';

import {
  TOOL_OUTPUT_CAP_CHARS,
  applyEvent,
  capToolOutput,
  emptyState,
  hydrateToolCall,
  type LiveToolCall,
  type SessionState
} from './conversation/reducer';

// Re-export so existing callers (components, tests) keep importing
// from `$lib/stores/conversation.svelte` without knowing a reducer
// module exists.
export { TOOL_OUTPUT_CAP_CHARS, capToolOutput, type LiveToolCall };

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
      state.toolCalls = [
        ...toolCalls.map(hydrateToolCall),
        ...state.toolCalls.filter((tc) => !toolCalls.some((row) => row.id === tc.id))
      ];
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
      setError: (msg) => {
        this.error = msg;
      },
      refreshMessages: (sessionId) => {
        void this.refreshMessages(sessionId);
      }
    });
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
