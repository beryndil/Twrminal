<script lang="ts">
  import { conversation } from '$lib/stores/conversation.svelte';
  import { replyActions } from '$lib/stores/replyActions.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import { copyText } from '$lib/utils/conversation-ui';
  import { BulkModeController } from '$lib/utils/bulk-mode.svelte';
  import { DragDropController } from '$lib/utils/composer-dragdrop-handlers.svelte';
  import { ReorgController } from '$lib/utils/reorg-actions.svelte';
  import ApprovalModal from '$lib/components/ApprovalModal.svelte';
  import ReplyActionPreview from '$lib/components/ReplyActionPreview.svelte';
  import AskUserQuestionModal from '$lib/components/AskUserQuestionModal.svelte';
  import BearingsMark from '$lib/components/icons/BearingsMark.svelte';
  import BulkActionBar from '$lib/components/BulkActionBar.svelte';
  import CheckpointGutter from '$lib/components/CheckpointGutter.svelte';
  import ConversationComposer, {
    type ConversationComposerHandle
  } from '$lib/components/ConversationComposer.svelte';
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
    getSectionEl: () => sectionEl
  });
  const reorg = new ReorgController({ exitBulkMode: () => bulk.clear() });

  function onJumpToAuditTarget(targetId: string): void {
    sessions.select(targetId);
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
        detail: { sessionId: sid, text: MORE_INFO_PROMPT }
      })
    );
  }

  /** L4.3.1 — `＋ SPAWN` action. Forwards to the store, which POSTs
   * `/api/sessions/{parent}/spawn_from_reply/{message_id}`, unshifts
   * the returned row, and selects it. The conversation pane swaps to
   * the new session via the existing `sessions.selected` reactive
   * chain. We deliberately don't await — the user wants immediate
   * feedback and the store handles error surfacing through
   * `sessions.error`. */
  function onSpawn(msg: api.Message): void {
    const sid = msg.session_id;
    if (!sid) return;
    void sessions.spawnFromReply(sid, msg.id);
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
  class="relative bg-slate-900 overflow-hidden flex flex-col min-w-0
    {dragdrop.dragging ? 'ring-2 ring-emerald-500/60 ring-inset' : ''}"
  ondragenter={(e) => dragdrop.onDragEnter(e)}
  ondragover={(e) => dragdrop.onDragOver(e)}
  ondragleave={(e) => dragdrop.onDragLeave(e)}
  ondrop={(e) => dragdrop.onDrop(e)}
>
  {#if dragdrop.dragging}
    <div
      class="pointer-events-none absolute inset-2 rounded border-2 border-dashed
        border-emerald-500/70 bg-slate-950/60 flex items-center justify-center z-20"
      data-testid="conversation-drop-hint"
    >
      <p class="text-sm text-emerald-300">Drop to attach file to the prompt</p>
    </div>
  {/if}
  {#if dragdrop.uploading}
    <div
      class="pointer-events-none absolute inset-2 rounded border-2 border-dashed
        border-sky-500/60 bg-slate-950/70 flex items-center justify-center z-20"
      data-testid="conversation-upload-hint"
    >
      <div class="flex flex-col items-center gap-3 text-sky-300">
        <BearingsMark size={56} spin label="Uploading file" />
        <p class="text-sm">Uploading dropped file…</p>
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
      class="pointer-events-none absolute inset-0 flex items-center justify-center
        bg-slate-950/60 backdrop-blur-sm z-30"
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

  <ReorgProposalEditor
    open={analyzeOpen}
    sessionId={sessions.selectedId}
    onClose={() => (analyzeOpen = false)}
    onApproved={() => (analyzeOpen = false)}
  />

  {#if conversation.highlightQuery}
    <div
      class="px-4 py-1.5 bg-amber-950/40 border-b border-amber-900/40
        flex items-center justify-between text-xs"
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
    class="relative flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4"
  >
    {#if conversation.hasMore}
      <p
        class="text-[10px] text-slate-600 text-center inline-flex items-center
          justify-center gap-1 self-center"
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
      <p class="text-slate-500 text-sm">No session selected.</p>
    {:else if conversation.messages.length === 0 && !conversation.streamingActive && audits.length === 0 && !conversation.loadingInitial}
      <p class="text-slate-500 text-sm">
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
            {onTldr}
            {onCritique}
            isLatestAssistant={item.turn.key === latestAssistantTurnKey}
            bulkMode={bulk.active}
            selectedIds={bulk.selectedIds}
            onToggleSelect={(msg, shift) =>
              bulk.toggleSelect(msg, shift, conversation.messages)}
            workingDir={sessions.selected?.working_dir ?? null}
          />
        {:else}
          <ReorgAuditDivider audit={item.audit} onJumpTo={onJumpToAuditTarget} />
        {/if}
      {/snippet}

      {#each timeline as item, idx (item.key)}
        {#if useVirtualization}
          {@const isStreamingTail = item.kind === 'turn' && item.turn.isStreaming}
          {@const inWarmTail = idx >= timeline.length - ALWAYS_WARM_TAIL}
          <VirtualItem
            scrollRoot={scrollContainer}
            forceVisible={isStreamingTail || inWarmTail}
          >
            {@render timelineEntry(item)}
          </VirtualItem>
        {:else}
          {@render timelineEntry(item)}
        {/if}
      {/each}

      {#if conversation.error}
        <article class="rounded border border-rose-900/50 px-3 py-2 bg-rose-950/30">
          <header class="text-[10px] uppercase tracking-wider text-rose-400 mb-1">
            error
          </header>
          <pre class="text-xs text-rose-300 whitespace-pre-wrap">{conversation.error}</pre>
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
