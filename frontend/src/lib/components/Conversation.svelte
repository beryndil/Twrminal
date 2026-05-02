<script lang="ts">
  import { goto } from '$app/navigation';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { replyActions } from '$lib/stores/replyActions.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import { formatBytes } from '$lib/attachments';
  import { copyText } from '$lib/utils/conversation-ui';
  import { BulkModeController } from '$lib/utils/bulk-mode.svelte';
  import { DragDropController } from '$lib/utils/composer-dragdrop-handlers.svelte';
  import { ReorgController } from '$lib/utils/reorg-actions.svelte';
  import ApprovalModal from '$lib/components/ApprovalModal.svelte';
  import ReplyActionPreview from '$lib/components/ReplyActionPreview.svelte';
  import SpawnClassifiedCard from '$lib/components/SpawnClassifiedCard.svelte';
  import * as checklists from '$lib/api/checklists';
  import AskUserQuestionModal from '$lib/components/AskUserQuestionModal.svelte';
  import BearingsMark from '$lib/components/icons/BearingsMark.svelte';
  import BulkActionBar from '$lib/components/BulkActionBar.svelte';
  import CheckpointGutter from '$lib/components/CheckpointGutter.svelte';
  import ConversationComposer, {
    type ConversationComposerHandle,
  } from '$lib/components/ConversationComposer.svelte';
  import AccentCards from '$lib/components/AccentCards.svelte';
  import ConversationHeader from '$lib/components/ConversationHeader.svelte';
  import LiveTodos from '$lib/components/LiveTodos.svelte';
  import MessageTurn from '$lib/components/MessageTurn.svelte';
  import ReorgAuditDivider from '$lib/components/ReorgAuditDivider.svelte';
  import ReorgPicker, { type ReorgPickerHandle } from '$lib/components/ReorgPicker.svelte';
  import ReorgProposalEditor from '$lib/components/ReorgProposalEditor.svelte';
  import ReorgUndoToast from '$lib/components/ReorgUndoToast.svelte';
  import SessionEdit from '$lib/components/SessionEdit.svelte';
  import VirtualItem from '$lib/components/VirtualItem.svelte';

  // Item 29 (2026-04-24 refactor): `turns` / `timeline` / `audits`
  // live on the store; the reducer keeps them in sync via in-place
  // tail mutation. See `reducer.ts` for the contract.
  const turns = $derived(conversation.turns);
  const timeline = $derived(conversation.timeline);
  const audits = $derived(conversation.audits);

  // Item 34: timeline virtualization. Below threshold the
  // IntersectionObserver-per-item cost isn't worth it; above, wrap
  // each entry in `VirtualItem` so only viewport-near items mount
  // their full MessageTurn. ALWAYS_WARM_TAIL keeps the streaming-tail
  // and auto-scroll-anchor items real (never placeholders).
  const VIRTUALIZE_THRESHOLD = 200;
  const ALWAYS_WARM_TAIL = 30;
  const useVirtualization = $derived(timeline.length > VIRTUALIZE_THRESHOLD);

  /** Turn key of the chronologically last turn with a finished
   * (non-streaming) assistant message. The "ℹ MORE" button only
   * renders on this turn (decision 2026-04-22 in TODO.md). The
   * in-place tail mutation leaves a streaming tail's `assistant`
   * field null, so the backwards scan naturally skips it. */
  const latestAssistantTurnKey = $derived.by((): string | null => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      if (turns[i].assistant !== null) return turns[i].key;
    }
    return null;
  });

  let scrollContainer: HTMLDivElement | undefined = $state();
  let editingSession = $state(false);
  let copiedMsgId = $state<string | null>(null);
  // Slice 6 of the Session Reorg plan: LLM-assisted / heuristic-
  // assisted analyzer modal. Open from the header's ✂ button. Cards
  // commit via `/reorg/split` per approved card; the modal owns its
  // own loading + per-card state.
  let analyzeOpen = $state(false);

  // Per-Conversation controllers. Each pane owns its own bulk-mode,
  // drop-state, and reorg/undo because all three are tab-local.
  const bulk = new BulkModeController();
  let composer: ConversationComposerHandle | undefined = $state();
  let picker: ReorgPickerHandle | undefined = $state();
  let sectionEl: HTMLElement | null = $state(null);
  const dragdrop = new DragDropController({
    attachFileAtCursor: (path, filename, sizeBytes) =>
      composer?.attachFileAtCursor(path, filename, sizeBytes),
    getSectionEl: () => sectionEl,
  });
  const reorg = new ReorgController({ exitBulkMode: () => bulk.clear() });

  function onJumpToAuditTarget(targetId: string): void {
    void goto(`/sessions/${encodeURIComponent(targetId)}`);
  }

  async function onCopyMessage(msg: api.Message): Promise<void> {
    if (!(await copyText(msg.content))) return;
    copiedMsgId = msg.id;
    setTimeout(() => {
      if (copiedMsgId === msg.id) copiedMsgId = null;
    }, 1500);
  }

  /** "More info" button on the most-recent assistant turn (decision
   * 2026-04-22 in TODO.md): pre-fill composer, no auto-send. The
   * dispatch reuses the same `bearings:composer-prefill` event the
   * regenerate action uses so the composer owns the focus side
   * effect in one place. */
  const MORE_INFO_PROMPT = 'Please go into more detail on your previous response.';
  function onMoreInfo(_msg: api.Message): void {
    const sid = sessions.selectedId;
    if (!sid) return;
    window.dispatchEvent(
      new CustomEvent('bearings:composer-prefill', {
        detail: { sessionId: sid, text: MORE_INFO_PROMPT },
      })
    );
  }

  /** L4.3.1 — `＋ SPAWN` action. Forwards to the store, which POSTs
   * `/api/sessions/{parent}/spawn_from_reply/{message_id}` and
   * unshifts the returned row. We then navigate to the new session's
   * deep-link URL so /sessions/[id]/+page.svelte handles select +
   * agent.connect via its URL→state effect. The store still sets
   * `selectedId` optimistically (so the row highlights immediately
   * even if the route mount races the unshift), and the route's
   * idempotent select call is a no-op when the id already matches. */
  async function onSpawn(msg: api.Message): Promise<void> {
    const sid = msg.session_id;
    if (!sid) return;
    const spawned = await sessions.spawnFromReply(sid, msg.id);
    if (spawned) {
      void goto(`/sessions/${encodeURIComponent(spawned.id)}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Wave 3 — classify-spawn state + handlers
  // ---------------------------------------------------------------------------

  /** The assistant message id that triggered the classify flow, or
   * null when no card is open.  Used in the template to decide which
   * turn should render the SpawnClassifiedCard below it. */
  let classifyMessageId = $state<string | null>(null);
  let classifyLoading = $state(false);
  let classifyResult = $state<api.SpawnClassifyResult | null>(null);

  /** `⊕ classify` button handler. Calls /classify and opens the card
   * below the triggering turn. If a card is already open for a
   * different message, the old one is replaced. */
  async function onSpawnClassify(msg: api.Message): Promise<void> {
    const sid = msg.session_id;
    if (!sid) return;
    classifyMessageId = msg.id;
    classifyLoading = true;
    classifyResult = null;
    try {
      classifyResult = await api.classifySpawn(sid, msg.id);
    } catch {
      // classifySpawn should not throw (server always returns 200);
      // guard anyway — close the card on unexpected network error.
      classifyMessageId = null;
    } finally {
      classifyLoading = false;
    }
  }

  function onClassifyCancel(): void {
    classifyMessageId = null;
    classifyResult = null;
    classifyLoading = false;
  }

  /** Apply the classifier's result. Drives the appropriate spawn
   * path per shape and navigates to the first created session.
   *
   * single_chat  → existing spawnFromReply (one call).
   * multi_chat   → spawnFromReply once per suggested item (N calls,
   *                same source message). Navigate to the first.
   * checklist    → createSession(kind=checklist) + createItem per
   *                suggested label. Navigate to the new session.
   */
  async function onClassifyApply(result: api.SpawnClassifyResult): Promise<void> {
    const msgId = classifyMessageId;
    const parent = sessions.selected;
    if (!msgId || !parent) return;
    onClassifyCancel();

    if (result.shape === 'single_chat') {
      // Existing path — simplest.
      const spawned = await sessions.spawnFromReply(parent.id, msgId);
      if (spawned) void goto(`/sessions/${encodeURIComponent(spawned.id)}`);
      return;
    }

    if (result.shape === 'multi_chat' && result.suggested_multi) {
      // Create N sessions from the same message. The server derives
      // title/desc from the reply each time; sessions are independent
      // threads for exploring each suggested approach.
      let firstId: string | null = null;
      for (const _item of result.suggested_multi) {
        const spawned = await sessions.spawnFromReply(parent.id, msgId);
        if (spawned && !firstId) firstId = spawned.id;
      }
      if (firstId) void goto(`/sessions/${encodeURIComponent(firstId)}`);
      return;
    }

    if (result.shape === 'checklist' && result.suggested_checklist) {
      const items = result.suggested_checklist;
      const firstLabel = items[0]?.label ?? 'Spawned checklist';
      try {
        const newSession = await api.createSession({
          working_dir: parent.working_dir,
          model: parent.model,
          title: firstLabel.slice(0, 60),
          description: `Classified spawn from session ${parent.id}`,
          tag_ids: [...parent.tag_ids],
          kind: 'checklist',
        });
        // Unshift into sidebar so it's immediately visible.
        sessions.list = [newSession, ...sessions.list.filter((s) => s.id !== newSession.id)];
        sessions.select(newSession.id);
        // Create all items in order.
        for (const item of items) {
          await checklists.createItem(newSession.id, { label: item.label, notes: item.notes });
        }
        void goto(`/sessions/${encodeURIComponent(newSession.id)}`);
      } catch {
        // Session creation failed — no partial state to clean up
        // (items are only created after the session exists).
      }
    }
  }

  /** L4.3.2 — `✂ TLDR` action. Hands the assistant message to the
   * `replyActions` store, which opens the shared preview modal and
   * streams the sub-agent's response into it. The store handles
   * cancel / cleanup; we just kick it off. The catalog refresh on
   * first invocation is fire-and-forget — if it fails the modal
   * falls back to the raw action name as the label, but the stream
   * still works. */
  function onTldr(msg: api.Message): void {
    if (!msg.session_id) return;
    if (Object.keys(replyActions.catalog).length === 0) {
      void replyActions.refreshCatalog();
    }
    replyActions.start('summarize', msg);
  }

  /** L4.3.3 — `⚔ CRIT` action. Same plumbing as `onTldr`; only the
   * action name changes. The shared `ReplyActionPreview` modal swaps
   * its label badge based on the catalog, so users get visual
   * confirmation of which sub-agent ran without us reaching into the
   * modal's internals. */
  function onCritique(msg: api.Message): void {
    if (!msg.session_id) return;
    if (Object.keys(replyActions.catalog).length === 0) {
      void replyActions.refreshCatalog();
    }
    replyActions.start('critique', msg);
  }

  /** L5.1 / Wave 1 lane 1 — `❝ QUOTE` action. Pre-fills the composer
   * with the assistant reply quoted line-by-line, followed by a blank
   * line so Dave's cursor lands on a fresh line for the follow-up.
   * Reuses the same `bearings:composer-prefill` event channel as the
   * regenerate / more-info actions; the composer owns the textarea
   * focus side effect in one place. No backend work — pure UI. */
  function onQuoteReply(msg: api.Message): void {
    const sid = sessions.selectedId;
    if (!sid) return;
    const quoted = msg.content
      .split('\n')
      .map((line) => `> ${line}`)
      .join('\n');
    window.dispatchEvent(
      new CustomEvent('bearings:composer-prefill', {
        detail: { sessionId: sid, text: `${quoted}\n\n` },
      })
    );
  }

  /** L5.1 / Wave 1 lane 2 — `⌗ CODE` action. Pulls the fenced code
   * blocks out of the reply, concatenates them with a blank line
   * between, and copies the result to the clipboard. Reuses the same
   * `copyText` toast machinery as the full-reply COPY button so the
   * user gets the same "✓ copied" confirmation. The button is
   * auto-hidden when the reply has no fenced blocks (see
   * `hasCodeBlocks` in MessageTurn) so this handler only ever fires
   * with content available. */
  const FENCED_CODE_RE = /```[ \t]*[\w+#-]*[ \t]*\n([\s\S]*?)```/g;
  function extractCodeBlocks(content: string): string {
    const blocks: string[] = [];
    let m: RegExpExecArray | null;
    FENCED_CODE_RE.lastIndex = 0;
    while ((m = FENCED_CODE_RE.exec(content)) !== null) {
      blocks.push(m[1].replace(/\n+$/, ''));
    }
    return blocks.join('\n\n');
  }
  async function onCopyCodeOnly(msg: api.Message): Promise<void> {
    const code = extractCodeBlocks(msg.content);
    if (!code) return;
    if (!(await copyText(code))) return;
    copiedMsgId = msg.id;
    setTimeout(() => {
      if (copiedMsgId === msg.id) copiedMsgId = null;
    }, 1500);
  }

  /** L5.1 / Wave 1 lane 3 — `⤓ SAVE` action. Builds a turn-scoped
   * JSON export — session metadata + the user prompt + the assistant
   * reply + the tool calls owned by this assistant message — and
   * triggers a browser download. Built client-side from data already
   * loaded into the conversation store; no backend round-trip
   * required. The shape mirrors the existing per-session
   * `/api/sessions/{id}/export` (snake_case fields) so a saved turn
   * looks like a one-turn slice of a session export. */
  function onExportTurn(msg: api.Message): void {
    const session = sessions.selected;
    if (!session) return;
    const turn = turns.find((t) => t.assistant?.id === msg.id);
    if (!turn) return;
    const messages: api.Message[] = [];
    if (turn.user) messages.push(turn.user);
    if (turn.assistant) messages.push(turn.assistant);
    const tool_calls = turn.toolCalls.map((tc) => ({
      id: tc.id,
      session_id: session.id,
      message_id: tc.messageId,
      name: tc.name,
      input: JSON.stringify(tc.input),
      output: tc.output,
      error: tc.error,
      ok: tc.ok,
      // LiveToolCall stores epoch-ms; the wire/store shape is ISO
      // strings. Round-trip via Date so the saved file matches what
      // the server would emit for the same turn.
      started_at: new Date(tc.startedAt).toISOString(),
      finished_at: tc.finishedAt !== null ? new Date(tc.finishedAt).toISOString() : null,
    }));
    const payload = { session, messages, tool_calls };
    const json = JSON.stringify(payload, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bearings-turn-${session.id.slice(0, 8)}-${msg.id.slice(0, 8)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Defer revoke so Chrome can complete the download dispatch.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  // Persistent reorg-audit dividers (Slice 5). Fetched on session
  // switch + on `updated_at` bumps so a move from the other end also
  // invalidates the list on refocus.
  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) return;
    void sessions.selected?.updated_at;
    void reorg.refreshAudits();
  });

  $effect(() => dragdrop.installSwallow());

  $effect(() => {
    void conversation.messages;
    void conversation.streamingText;
    if (scrollContainer) {
      queueMicrotask(() => {
        if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
      });
    }
  });

  const SCROLL_TOP_THRESHOLD = 40;

  $effect(() => {
    const el = scrollContainer;
    if (!el) return;
    async function onScroll() {
      if (!el) return;
      if (el.scrollTop > SCROLL_TOP_THRESHOLD) return;
      if (!conversation.hasMore || conversation.loadingOlder) return;
      const prevHeight = el.scrollHeight;
      await conversation.loadOlder();
      // Preserve viewport: after prepend, keep the first-previously-
      // visible message in the same screen position.
      if (el) el.scrollTop = el.scrollHeight - prevHeight;
    }
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  });

  // Document-level Esc clears an active search highlight. Scoped to
  // this component so it only binds while a session is open; the
  // textarea keeps its own Esc handling via browser defaults.
  $effect(() => {
    function onDocKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      if (!conversation.highlightQuery) return;
      // Don't hijack Esc while the user is typing a prompt.
      const active = document.activeElement;
      const inTextarea = active?.tagName === 'TEXTAREA' || active?.tagName === 'INPUT';
      if (inTextarea) return;
      conversation.highlightQuery = '';
    }
    document.addEventListener('keydown', onDocKey);
    return () => document.removeEventListener('keydown', onDocKey);
  });
</script>

<SessionEdit bind:open={editingSession} sessionId={sessions.selectedId} />

<ReorgPicker bind:this={picker} controller={reorg} />

{#if reorg.undo}
  <ReorgUndoToast
    message={reorg.undo.message}
    warnings={reorg.undo.warnings}
    onUndo={reorg.undo.run}
    onDismiss={() => reorg.dismissUndo()}
  />
{/if}

{#if bulk.active}
  <BulkActionBar
    count={bulk.count}
    onMove={() => picker?.openBulkMove(bulk.ids())}
    onSplit={() => picker?.openBulkSplit(bulk.ids())}
    onCancel={() => bulk.toggle()}
  />
{/if}

{#if conversation.pendingApproval}
  {#if conversation.pendingApproval.tool_name === 'AskUserQuestion'}
    <!-- AskUserQuestion is a Claude Code built-in whose answers are
         collected by the permission component and handed to the SDK
         via `PermissionResultAllow.updated_input`. The generic
         ApprovalModal's approve/deny gate can't express that, so we
         route it to a dedicated picker that renders options and
         builds the `answers` payload. -->
    <AskUserQuestionModal
      request={conversation.pendingApproval}
      connected={agent.state === 'open'}
      onRespond={(id, decision, reason, updatedInput) =>
        agent.respondToApproval(id, decision, reason, updatedInput)}
    />
  {:else}
    <ApprovalModal
      request={conversation.pendingApproval}
      connected={agent.state === 'open'}
      onRespond={(id, decision, reason) => agent.respondToApproval(id, decision, reason)}
    />
  {/if}
{/if}

<!-- L4.3.2 — Reply-action preview modal. Always mounted; it owns
     its own visibility off `replyActions.state.status !== 'idle'`.
     Generic by design so L4.3.3's `⚔ CRIT` reuses this same component
     without modification. -->
<ReplyActionPreview />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<section
  bind:this={sectionEl}
  class="relative flex min-w-0 flex-col overflow-hidden bg-slate-900
    {dragdrop.dragging ? 'ring-2 ring-inset ring-emerald-500/60' : ''}"
  ondragenter={(e) => dragdrop.onDragEnter(e)}
  ondragover={(e) => dragdrop.onDragOver(e)}
  ondragleave={(e) => dragdrop.onDragLeave(e)}
  ondrop={(e) => dragdrop.onDrop(e)}
>
  {#if dragdrop.dragging}
    <div
      class="pointer-events-none absolute inset-2 z-20 flex items-center
        justify-center rounded border-2 border-dashed border-emerald-500/70 bg-slate-950/60"
      data-testid="conversation-drop-hint"
    >
      <p class="text-sm text-emerald-300">Drop to attach file to the prompt</p>
    </div>
  {/if}
  {#if dragdrop.uploading}
    <div
      class="pointer-events-none absolute inset-2 z-20 flex items-center
        justify-center rounded border-2 border-dashed border-sky-500/60 bg-slate-950/70"
      data-testid="conversation-upload-hint"
    >
      <div class="flex w-72 max-w-[80%] flex-col items-center gap-3 text-sky-300">
        <BearingsMark size={56} spin label="Uploading file" />
        <p class="w-full truncate text-center text-sm" data-testid="upload-label">
          {dragdrop.uploadLabel ? `Uploading ${dragdrop.uploadLabel}…` : 'Uploading dropped file…'}
        </p>
        <!-- Determinate bar when the browser handed us a total; marquee
             when it didn't (chunked encoding, redirects). The width
             calc clamps at 100 so a buggy ProgressEvent reporting
             loaded > total can't overflow the bar. -->
        {#if dragdrop.uploadProgress && dragdrop.uploadProgress.total != null && dragdrop.uploadProgress.total > 0}
          {@const total = dragdrop.uploadProgress.total}
          {@const loaded = dragdrop.uploadProgress.loaded}
          {@const pct = Math.min(100, Math.round((loaded / total) * 100))}
          <div
            class="h-1.5 w-full overflow-hidden rounded bg-slate-800"
            data-testid="upload-progress-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <div
              class="h-full bg-sky-500 transition-[width] duration-150 ease-out"
              style="width: {pct}%"
            ></div>
          </div>
          <p class="text-[11px] text-sky-400/80">
            {formatBytes(loaded)} / {formatBytes(total)} · {pct}%
          </p>
        {:else if dragdrop.uploadProgress}
          <!-- Indeterminate fallback: render a faint marquee so the
               operator sees motion even when bytes/sec aren't known. -->
          <div
            class="relative h-1.5 w-full overflow-hidden rounded bg-slate-800"
            data-testid="upload-progress-bar-indeterminate"
            role="progressbar"
          >
            <div class="h-full w-1/3 animate-pulse bg-sky-500/60" style="margin-left: 33%"></div>
          </div>
          <p class="text-[11px] text-sky-400/80">
            {formatBytes(dragdrop.uploadProgress.loaded)} sent
          </p>
        {/if}
      </div>
    </div>
  {/if}
  {#if conversation.loadingInitial}
    <!-- Full-pane overlay spinner. Painted in the same frame as the
         click (agent.connect yields a paint frame right after flipping
         loadingInitial), so it's visible BEFORE the REST fetch +
         MessageTurn re-render pin the main thread. Without this the
         user sees the whole app freeze on click and only after the
         hang does the new session appear. pointer-events-none so it
         doesn't block keyboard focus on the textarea below; z-30 puts
         it above drag + upload hints but below the approval modal. -->
    <div
      class="pointer-events-none absolute inset-0 z-30 flex items-center
        justify-center bg-slate-950/60 backdrop-blur-sm"
      data-testid="conversation-initial-loading"
    >
      <div class="flex flex-col items-center gap-3 text-sky-300">
        <BearingsMark size={80} spin label="Loading session" />
        <p class="text-xs uppercase tracking-wider text-slate-400">Loading session…</p>
      </div>
    </div>
  {/if}

  <ConversationHeader
    bulkMode={bulk.active}
    onToggleBulk={() => bulk.toggle()}
    onOpenMerge={() => picker?.openMerge()}
    onOpenAnalyze={() => (analyzeOpen = true)}
    onEditSession={() => (editingSession = true)}
  />

  <!-- Phase 2b of the v1.0.0 dashboard redesign — summary badges
       above the chat (token caching savings + recovery capability).
       Auto-suppresses when no session is selected, so the empty-state
       pane stays empty. -->
  <AccentCards />

  <ReorgProposalEditor
    open={analyzeOpen}
    sessionId={sessions.selectedId}
    onClose={() => (analyzeOpen = false)}
    onApproved={() => (analyzeOpen = false)}
  />

  {#if conversation.highlightQuery}
    <div
      class="flex items-center justify-between border-b border-amber-900/40
        bg-amber-950/40 px-4 py-1.5 text-xs"
    >
      <span class="text-amber-200">
        Matching <span class="font-mono">«{conversation.highlightQuery}»</span> · Esc to clear
      </span>
      <button
        type="button"
        class="text-amber-400 hover:text-amber-200"
        aria-label="Clear highlight"
        onclick={() => (conversation.highlightQuery = '')}
      >
        ✕
      </button>
    </div>
  {/if}

  {#if sessions.selectedId}
    <CheckpointGutter sessionId={sessions.selectedId} />
  {/if}

  {#if conversation.todos !== null}
    <!-- Sits between the session header (or CheckpointGutter, when
         checkpoints exist) and the scrollable message area. Previously
         nested inside the scroll container with `sticky top-0` and
         negative margins to cancel parent padding — the padding gap
         above the card was too stubborn, and since the widget was
         always pinned to the top anyway, hoisting it out is simpler
         and hugs the element above it cleanly. -->
    <LiveTodos todos={conversation.todos} />
  {/if}

  <div
    bind:this={scrollContainer}
    class="relative flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
  >
    {#if conversation.hasMore}
      <p
        class="inline-flex items-center justify-center gap-1 self-center
          text-center text-[10px] text-slate-600"
      >
        {#if conversation.loadingOlder}
          <BearingsMark size={10} spin label="Loading older messages" />
          Loading older…
        {:else}
          Scroll up to load older messages
        {/if}
      </p>
    {/if}
    {#if !sessions.selectedId}
      <p class="text-sm text-slate-500">No session selected.</p>
    {:else if conversation.messages.length === 0 && !conversation.streamingActive && audits.length === 0 && !conversation.loadingInitial}
      <p class="text-sm text-slate-500">
        No messages yet. Send a prompt to start the conversation.
      </p>
    {:else}
      {#snippet timelineEntry(item: (typeof timeline)[number])}
        {#if item.kind === 'turn'}
          <MessageTurn
            user={item.turn.user}
            assistant={item.turn.assistant}
            thinking={item.turn.thinking}
            toolCalls={item.turn.toolCalls}
            streamingContent={item.turn.streamingContent}
            streamingThinking={item.turn.streamingThinking}
            isStreaming={item.turn.isStreaming}
            highlightQuery={conversation.highlightQuery}
            {copiedMsgId}
            {onCopyMessage}
            {onMoreInfo}
            {onSpawn}
            {onSpawnClassify}
            {onTldr}
            {onCritique}
            {onQuoteReply}
            {onCopyCodeOnly}
            {onExportTurn}
            isLatestAssistant={item.turn.key === latestAssistantTurnKey}
            bulkMode={bulk.active}
            selectedIds={bulk.selectedIds}
            onToggleSelect={(msg, shift) => bulk.toggleSelect(msg, shift, conversation.messages)}
            workingDir={sessions.selected?.working_dir ?? null}
          />
          {#if item.turn.assistant?.id === classifyMessageId}
            <!-- Wave 3: SpawnClassifiedCard sits directly below the
                 turn whose assistant message triggered /classify. -->
            <SpawnClassifiedCard
              result={classifyResult}
              loading={classifyLoading}
              onApply={onClassifyApply}
              onCancel={onClassifyCancel}
            />
          {/if}
        {:else}
          <ReorgAuditDivider audit={item.audit} onJumpTo={onJumpToAuditTarget} />
        {/if}
      {/snippet}

      {#each timeline as item, idx (item.key)}
        {#if useVirtualization}
          {@const isStreamingTail = item.kind === 'turn' && item.turn.isStreaming}
          {@const inWarmTail = idx >= timeline.length - ALWAYS_WARM_TAIL}
          <VirtualItem scrollRoot={scrollContainer} forceVisible={isStreamingTail || inWarmTail}>
            {@render timelineEntry(item)}
          </VirtualItem>
        {:else}
          {@render timelineEntry(item)}
        {/if}
      {/each}

      {#if conversation.error}
        <article class="rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2">
          <header class="mb-1 text-[10px] uppercase tracking-wider text-rose-400">error</header>
          <pre class="whitespace-pre-wrap text-xs text-rose-300">{conversation.error}</pre>
        </article>
      {/if}
    {/if}
  </div>

  <ConversationComposer bind:this={composer} {dragdrop} />
</section>

<style>
  /* Search-mark uses the `--color-mark-*` semantic aliases so the
     highlight contrast tracks the active theme. The aliases resolve
     to channel triples (no commas) so `rgb(... / alpha)` opacity
     modulation still works. paper-light overrides --color-mark-text
     to a dark amber so the text stays readable on the lighter
     transparent fill. */
  :global(mark.search-mark) {
    background-color: rgb(var(--color-mark-bg) / 0.35);
    color: rgb(var(--color-mark-text));
    border-radius: 0.125rem;
    padding: 0 0.125rem;
  }
</style>
