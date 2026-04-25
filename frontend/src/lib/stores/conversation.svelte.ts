import * as api from '$lib/api';
import type { MessageAttachment } from '$lib/api/sessions';
import { sessions } from '$lib/stores/sessions.svelte';
import type { Turn } from '$lib/turns';

import {
  TOOL_OUTPUT_CAP_CHARS,
  appendUserTurn,
  applyEvent,
  capToolOutput,
  emptyState,
  hydrateToolCall,
  rebuildTurnsFromMessages,
  recomputeTimeline,
  type ContextUsageState,
  type LiveToolCall,
  type SessionState,
  type TimelineItem
} from './conversation/reducer';

// Re-export so existing callers (components, tests) keep importing
// from `$lib/stores/conversation.svelte` without knowing a reducer
// module exists.
export {
  TOOL_OUTPUT_CAP_CHARS,
  capToolOutput,
  type ContextUsageState,
  type LiveToolCall,
  type TimelineItem,
  type Turn
};

const PAGE_SIZE = 50;

/** Minimum time (ms) the `loadingInitial` overlay stays visible once
 * shown. Without this, a fast REST load (cached session, warm DB) can
 * mount and unmount the overlay inside a single compositor tick and the
 * user sees nothing — exactly the "it's selective about when it shows"
 * symptom. 250ms is under the human flicker-perception threshold for a
 * reappearing visual, so it always reads as "brief loading state" rather
 * than "janky flash." Tests bypass via `import.meta.env.TEST` because
 * fake timers don't advance the deferred clear. */
const MIN_LOADING_VISIBLE_MS = 250;

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

  // Per-session bookkeeping for the `loadingInitial` minimum-display
  // debounce. Kept outside the reactive state map so flipping the
  // timestamp doesn't invalidate view subscribers — only `loadingInitial`
  // on the state row is visible to templates.
  private loadingInitialStartedAt: Record<string, number> = {};
  private loadingInitialClearTimer: Record<string, ReturnType<typeof setTimeout>> = {};

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
  // Per-session view caches (item 29 / 2026-04-24): the reducer keeps
  // these in sync with the wire state via in-place mutation, so the
  // Conversation pane reads them directly instead of re-deriving on
  // every WS frame. See `reducer.ts` module docstring for the
  // mutation contract.
  turns = $derived<Turn[]>(this.active()?.turns ?? []);
  audits = $derived<api.ReorgAudit[]>(this.active()?.audits ?? []);
  timeline = $derived<TimelineItem[]>(this.active()?.timeline ?? []);
  hasMore = $derived<boolean>(this.active()?.hasMore ?? false);
  pendingApproval = $derived<api.ApprovalRequestEvent | null>(
    this.active()?.pendingApproval ?? null
  );
  contextUsage = $derived<ContextUsageState | null>(this.active()?.contextUsage ?? null);
  todos = $derived<api.TodoItem[] | null>(this.active()?.todos ?? null);
  // True while `load()` is in flight for the active session. The
  // Conversation pane reads this to show a centered BearingsMark
  // spinner on click until the first page of messages lands, which
  // is noticeable for large sessions (lots of tool calls / long
  // message windows). Per-session under the hood so rapid A→B→A
  // clicks don't cross-wire.
  loadingInitial = $derived<boolean>(this.active()?.loadingInitial ?? false);

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

  /** Flip the per-session `loadingInitial` flag with a minimum-visible
   * debounce on the false→true→false → false transition.
   *
   * The `true` branch is called from `agent.connect()` *before* it
   * yields a paint frame, so the pane's overlay spinner shows up in
   * the same frame as the click — the subsequent REST fetch + Svelte
   * render of the MessageTurn tree would otherwise pin the main thread
   * before any spinner got to paint, which is the "entire app hangs
   * on click" failure mode. `load()` routes through here too as a
   * safety net for callers (reconcile-after-reorg, etc.) that skip
   * `agent.connect`.
   *
   * The `false` branch enforces `MIN_LOADING_VISIBLE_MS` so fast loads
   * (cached session, warm REST) still hold the overlay up long enough
   * for the compositor to commit at least one visible frame. Without
   * this, the mount+unmount pair can land inside a single tick and the
   * user sees nothing — the "indicator is selective about when it
   * appears" symptom. If a pending clear is outstanding and a new
   * `true` arrives (rapid re-click), we cancel it and reset the start
   * so the next `false` gets a fresh 250ms window. */
  markLoadingInitial(sessionId: string, flag: boolean): void {
    const state = this.ensureState(sessionId);
    const pending = this.loadingInitialClearTimer[sessionId];
    if (pending) {
      clearTimeout(pending);
      delete this.loadingInitialClearTimer[sessionId];
    }
    if (flag) {
      state.loadingInitial = true;
      this.loadingInitialStartedAt[sessionId] = performance.now();
      return;
    }
    // Test bypass: vitest's fake timers stall the deferred clear, and
    // the minimum-display is purely a paint-flicker concern with no
    // semantic value in jsdom. Flip directly so tests stay deterministic.
    if (import.meta.env.TEST) {
      state.loadingInitial = false;
      delete this.loadingInitialStartedAt[sessionId];
      return;
    }
    const startedAt = this.loadingInitialStartedAt[sessionId];
    const elapsed = startedAt != null ? performance.now() - startedAt : Infinity;
    if (elapsed >= MIN_LOADING_VISIBLE_MS) {
      state.loadingInitial = false;
      delete this.loadingInitialStartedAt[sessionId];
      return;
    }
    const remaining = MIN_LOADING_VISIBLE_MS - elapsed;
    this.loadingInitialClearTimer[sessionId] = setTimeout(() => {
      delete this.loadingInitialClearTimer[sessionId];
      delete this.loadingInitialStartedAt[sessionId];
      const s = this.states[sessionId];
      if (s) s.loadingInitial = false;
    }, remaining);
  }

  async load(sessionId: string): Promise<api.Session | null> {
    this.sessionId = sessionId;
    const state = this.ensureState(sessionId);
    this.error = null;
    // Flip the per-session loading flag *before* the first await so
    // the spinner is visible in the same reactive tick as the click.
    // Cleared in the finally below — covers both success and error
    // so a failed fetch doesn't leave the pane showing a stale
    // spinner forever. `agent.connect()` sets this earlier (before
    // yielding a paint frame) for the click path; this call is a
    // safety net for direct-load callers (reorg reconcile, etc.).
    // Routed through markLoadingInitial so the debounce bookkeeping
    // stays consistent regardless of entry point.
    this.markLoadingInitial(sessionId, true);
    try {
      // Fetch the first message page first so we can scope the
      // tool_calls lookup to just those messages. Pre-v0.x.x we pulled
      // every tool_call for the session on every load(); sessions with
      // thousands of historical tool_calls made that a 2 MB+ payload
      // and a full-table scan per navigation. The follow-ups (session
      // row + todos) don't depend on the page, so they run in parallel
      // with the page fetch. Tool-calls waits on the page.
      const [session, page, todos] = await Promise.all([
        api.getSession(sessionId),
        api.listMessagesPage(sessionId, { limit: PAGE_SIZE }),
        api.getSessionTodos(sessionId)
      ]);
      const toolCalls = await api.listToolCalls(sessionId, {
        messageIds: page.messages.map((m) => m.id)
      });
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
      // Rebuild the turns + timeline view caches from the freshly
      // loaded messages. Audits land separately via `setAudits` once
      // `Conversation.svelte`'s effect fires `listReorgAudits`.
      rebuildTurnsFromMessages(state);
      recomputeTimeline(state);
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
    } finally {
      this.markLoadingInitial(sessionId, false);
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
      // Now that listToolCalls is scoped to the visible message window
      // (see load()), paginating older messages has to pull the
      // matching tool_calls too — otherwise the ToolDrawer under those
      // older messages would render empty rows. Fetch both in parallel
      // so an infinite-scroll tick costs one round-trip.
      const olderIds = page.messages.map((m) => m.id);
      const olderToolCalls = olderIds.length
        ? await api.listToolCalls(this.sessionId, { messageIds: olderIds })
        : [];
      state.messages = [...page.messages, ...state.messages];
      state.hasMore = page.hasMore;
      for (const m of page.messages) state.completedMessageIds.add(m.id);
      // Merge: keep any live/unacknowledged tool_calls already on state
      // and append hydrated rows for the new page. De-dupe by id in
      // case a streaming tool_call finished between the page fetch and
      // the tool_calls fetch — the DB row wins (finalised output).
      const hydrated = olderToolCalls.map(hydrateToolCall);
      const hydratedIds = new Set(hydrated.map((tc) => tc.id));
      state.toolCalls = [
        ...hydrated,
        ...state.toolCalls.filter((tc) => !hydratedIds.has(tc.id))
      ];
      // Older messages prepend to the array → rebuild both caches so
      // the new turns land at the top in chronological order. Audits
      // tied to those older positions will resort on the next
      // `setAudits` if any were missing from the initial load.
      rebuildTurnsFromMessages(state);
      recomputeTimeline(state);
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

  pushUserMessage(
    sessionId: string,
    content: string,
    attachments: MessageAttachment[] = []
  ): void {
    const state = this.ensureState(sessionId);
    const msg: api.Message = {
      id: crypto.randomUUID().replaceAll('-', ''),
      session_id: sessionId,
      role: 'user',
      content,
      thinking: null,
      created_at: new Date().toISOString(),
      // Null (not empty array) for attachment-free sends so the
      // optimistic row matches the shape `GET /messages` returns
      // for pre-0027 rows — keeps render-branch code that checks
      // `msg.attachments?.length` honest.
      attachments: attachments.length > 0 ? attachments : null
    };
    state.messages = [...state.messages, msg];
    // Append a matching open user turn + timeline item so the new
    // prompt paints immediately. `message_start` will absorb this
    // turn into the streaming tail when the agent starts responding.
    appendUserTurn(state, msg);
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
    // The patched message object is a fresh reference; existing Turn
    // entries still point at the stale one. Rebuild the view caches
    // so the pin / hide flag flips paint immediately. Cold path —
    // user-initiated context-menu action, not per-WS-event.
    rebuildTurnsFromMessages(state);
    recomputeTimeline(state);
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
      rebuildTurnsFromMessages(state);
      recomputeTimeline(state);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  /** Replace the per-session reorg-audit list and re-merge it into
   * the timeline. Called from `Conversation.svelte`'s `refreshAudits`
   * effect when the session's audit list is fetched / refreshed.
   * Audit timestamps don't shift mid-stream, so a single rebuild on
   * fetch is enough — the per-event reducer paths never touch
   * audits. */
  setAudits(sessionId: string, audits: api.ReorgAudit[]): void {
    const state = this.states[sessionId];
    if (!state) return;
    state.audits = audits;
    recomputeTimeline(state);
  }
}

export const conversation = new ConversationStore();
