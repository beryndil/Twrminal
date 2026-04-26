<script lang="ts">
  /**
   * Header strip for the Conversation pane.
   *
   * Renders: paired-checklist breadcrumb (when the session was spawned
   * from a checklist item), session title + working dir + model + cost
   * pill or token meter, message-count + context meter, tag chips,
   * description plug (clamped at 3 lines with show-more toggle), and
   * the right-side button cluster (permission mode, Stop/Undo, edit /
   * export / copy / bulk-toggle / merge / close, connection badge).
   *
   * Owns the header-only effects: paired-crumb resolution, tag chip
   * fetch, subscription token totals, and the description-overflow
   * snap-back guard. Lives outside `Conversation.svelte` so the parent
   * shrinks under the project's 400-line cap.
   */
  import { billing } from '$lib/stores/billing.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import {
    connectionLabel,
    copyText,
    messagesAsMarkdown,
    pressureClass
  } from '$lib/utils/conversation-ui';
  import BearingsMark from './icons/BearingsMark.svelte';
  import ContextMeter from './ContextMeter.svelte';
  import PermissionModeSelector from './PermissionModeSelector.svelte';
  import StopUndoInline from './StopUndoInline.svelte';
  import TokenMeter from './TokenMeter.svelte';

  let {
    bulkMode,
    onToggleBulk,
    onOpenMerge,
    onOpenAnalyze,
    onEditSession
  }: {
    bulkMode: boolean;
    onToggleBulk: () => void;
    onOpenMerge: () => void;
    /** Slice 6 of the Session Reorg plan. Opens the analyze-and-reorg
     * modal — heuristic / LLM analyzer that proposes splits, with
     * per-card editing + per-card approval committed via
     * `/reorg/split`. Server returns proposals only; the actual
     * splits run client-side. */
    onOpenAnalyze: () => void;
    onEditSession: () => void;
  } = $props();

  let exporting = $state(false);
  let copiedSession = $state(false);

  /** Toggle the active session's closed flag. No confirmation dialog —
   * a closed session is trivially reopenable and lives one click away
   * in the sidebar's "Closed" group. */
  async function onToggleClosed(): Promise<void> {
    const sid = sessions.selectedId;
    if (!sid) return;
    const current = sessions.selected;
    if (!current) return;
    if (current.closed_at) {
      await sessions.reopen(sid);
    } else {
      await sessions.close(sid);
    }
  }

  async function onCopySession(): Promise<void> {
    const sid = sessions.selectedId;
    if (!sid || copiedSession) return;
    // Pull the full list so the copy isn't limited to what's paged in.
    const dump = await api.exportSession(sid);
    if (!(await copyText(messagesAsMarkdown(dump.messages)))) return;
    copiedSession = true;
    setTimeout(() => (copiedSession = false), 1500);
  }

  async function onExport(): Promise<void> {
    const sid = sessions.selectedId;
    if (!sid || exporting) return;
    exporting = true;
    try {
      const dump = await api.exportSession(sid);
      const blob = new Blob([JSON.stringify(dump, null, 2)], {
        type: 'application/json'
      });
      const url = URL.createObjectURL(blob);
      const day = new Date().toISOString().slice(0, 10).replaceAll('-', '');
      const name = `session-${sid.slice(0, 8)}-${day}.json`;
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      exporting = false;
    }
  }

  // Header session-description clamp. Long plugs (multi-paragraph
  // design briefs, bug-report pastes) would otherwise eat half the
  // viewport above the conversation — we collapse to 3 lines with a
  // "show more" toggle and re-measure whenever the session or its
  // description changes.
  //
  // Snap-back guard (2026-04-25): the effect tracks the sessions.selected
  // proxy, which the WS layer replaces on every routine session update
  // (message_count bumps, token totals, paired-crumb refreshes). An
  // unconditional `descriptionExpanded = false` on every run meant any
  // user click of "show more" got reverted within a tick by the next
  // routine update. We snapshot id+description into a plain string and
  // only reset expanded when the snapshot actually changes.
  let descriptionEl: HTMLParagraphElement | undefined = $state();
  let descriptionExpanded = $state(false);
  let descriptionOverflows = $state(false);
  let descriptionSnapshot = '';

  $effect(() => {
    const sid = sessions.selected?.id ?? '';
    const text = sessions.selected?.description ?? '';
    const snapshot = sid + '::' + text;
    if (snapshot !== descriptionSnapshot) {
      descriptionExpanded = false;
      descriptionSnapshot = snapshot;
    }
    if (!sid || !text || !descriptionEl) {
      descriptionOverflows = false;
      return;
    }
    // Measure on the next microtask so the clamp class has applied
    // before we compare scroll vs client height.
    const el = descriptionEl;
    queueMicrotask(() => {
      descriptionOverflows = el.scrollHeight > el.clientHeight + 1;
    });
  });

  // Paired-chat breadcrumb (v0.5.0, Slice 4 of nimble-checking-heron).
  // When the selected session was spawned from a checklist item, we
  // resolve the item + parent title so the header can render a
  // clickable "📋 parent-title › item-label" trail back to the source.
  // Refetches on session change; silent on 404 because the pairing
  // may have been severed (checklist or item deleted) between renders.
  type PairedChatCrumb = {
    parentId: string;
    parentTitle: string;
    itemId: number;
    itemLabel: string;
  };
  let pairedCrumb = $state<PairedChatCrumb | null>(null);
  // Memoize the last successfully-resolved crumb keyed on
  // `sid:itemId`. The `sessions.svelte.ts` `softRefresh` poll
  // replaces `sessions.list` with new object references every 3 s,
  // which would otherwise re-fire this effect and re-issue
  // `getChecklist()` against every candidate every tick. We only
  // need to re-resolve when either the selected session id or its
  // `checklist_item_id` actually changes.
  let resolvedFor = $state<string | null>(null);

  $effect(() => {
    const current = sessions.selected;
    if (!current || current.checklist_item_id == null) {
      pairedCrumb = null;
      resolvedFor = null;
      return;
    }
    const sid = current.id;
    const itemId = current.checklist_item_id;
    const key = `${sid}:${itemId}`;
    if (resolvedFor === key && pairedCrumb) return;
    // The item's parent checklist id is whichever session ids we
    // already have in the sidebar store — scan for the one whose
    // `kind === 'checklist'` with a matching item. The lookup is
    // cheap (sidebar list is typically <100 entries) and avoids
    // adding a dedicated reverse-lookup endpoint. If the parent
    // isn't in the store (e.g. fresh page load, sidebar still
    // loading), skip this pass and the effect reruns when the list
    // updates.
    const parent = sessions.list.find(
      (s) => s.kind === 'checklist' && s.id !== sid
    );
    // Fallback path: fetch the item + checklist so the breadcrumb
    // still renders even when the parent isn't in the sidebar yet.
    // Use the item's `checklist_id` (== parent session id) so we
    // don't need to guess.
    (async () => {
      // Probe every candidate checklist until one returns the item
      // we care about. In practice the sidebar carries the parent
      // for any recently-opened paired chat, so this rarely fans
      // out beyond one call.
      const candidates = parent
        ? [parent]
        : sessions.list.filter((s) => s.kind === 'checklist');
      for (const cand of candidates) {
        try {
          const checklist = await api.getChecklist(cand.id);
          const match = checklist.items.find((i) => i.id === itemId);
          if (match && sessions.selected?.id === sid) {
            pairedCrumb = {
              parentId: cand.id,
              parentTitle: cand.title ?? '(untitled checklist)',
              itemId: match.id,
              itemLabel: match.label
            };
            resolvedFor = key;
            return;
          }
        } catch {
          // Deleted or inaccessible — try the next candidate.
        }
      }
      if (sessions.selected?.id === sid) pairedCrumb = null;
    })();
  });

  // Tag chips in the header. Refetch on session change and on
  // `updated_at` bumps (SessionEdit attach/detach bumps the server).
  let sessionTags = $state<api.Tag[]>([]);

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    void sessions.selected?.updated_at;
    if (!sid) {
      sessionTags = [];
      return;
    }
    api.listSessionTags(sid).then(
      (r) => (sessionTags = r),
      () => {}
    );
  });

  // Subscription-mode token totals for the header. Only fetched when
  // billing mode is `subscription` — PAYG users never hit the endpoint
  // and the meter is not rendered. Refreshed on session change and
  // whenever a streaming turn completes (streamingActive true → false),
  // which is the same cadence at which `total_cost_usd` would move.
  let tokenTotals = $state<api.TokenTotals | null>(null);
  let prevStreaming = false;

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid || !billing.showTokens) {
      tokenTotals = null;
      return;
    }
    // Fetch once on session change. The completion effect below
    // handles subsequent refreshes.
    api.getSessionTokens(sid).then(
      (r) => {
        if (sessions.selected?.id === sid) tokenTotals = r;
      },
      () => {
        // Non-fatal — leave the prior totals (or null placeholder) in
        // place. /tokens failing does not warrant a visible error.
      }
    );
  });

  $effect(() => {
    const active = conversation.streamingActive;
    const sid = sessions.selected?.id ?? null;
    if (!sid || !billing.showTokens) {
      prevStreaming = active;
      return;
    }
    // Trailing edge: a turn just finished. Refresh the aggregate so
    // the meter reflects the new per-turn usage. Using an edge trigger
    // (rather than a timer) keeps this cheap — one fetch per turn.
    if (prevStreaming && !active) {
      api.getSessionTokens(sid).then(
        (r) => {
          if (sessions.selected?.id === sid) tokenTotals = r;
        },
        () => {}
      );
    }
    prevStreaming = active;
  });
</script>

<header class="border-b border-slate-800 px-4 py-3 flex items-baseline justify-between">
  <div class="min-w-0">
    {#if pairedCrumb}
      <nav
        class="mb-1 flex items-center gap-1 text-xs text-slate-500"
        aria-label="Paired checklist item"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1 hover:text-sky-400"
          onclick={() => sessions.select(pairedCrumb!.parentId)}
          title="Back to checklist"
        >
          <span aria-hidden="true">📋</span>
          <span class="max-w-[16ch] truncate">{pairedCrumb.parentTitle}</span>
        </button>
        <span aria-hidden="true">›</span>
        <span class="max-w-[24ch] truncate text-slate-300">{pairedCrumb.itemLabel}</span>
      </nav>
    {/if}
    <h1 class="text-lg font-medium flex items-center gap-2">
      <!-- Permanent brand mark. Spins reactively while the agent is
           connecting, a response is streaming, or the per-session REST
           bundle is still in flight after a click. The logo IS the
           work indicator, so loading states read as the app coming
           alive rather than as bolted-on spinners. `loadingInitial`
           is what catches the "session clicked, big transcript still
           loading" case — WS replay usually paints messages before
           REST finishes, so the centered-pane spinner rarely gets a
           chance to render; this header mark keeps a steady signal
           while tool calls / audits / tags / tokens are still
           streaming in behind the scenes. -->
      <BearingsMark
        size={20}
        spin={agent.state === 'connecting' ||
          conversation.streamingActive ||
          conversation.loadingInitial}
      />
      {sessions.selected?.title ?? 'Bearings'}
      {#if sessions.selected}
        <button
          type="button"
          class="text-xs text-slate-500 hover:text-slate-300"
          aria-label="Edit session"
          title="Edit title / budget"
          onclick={onEditSession}
        >
          ✎
        </button>
        <button
          type="button"
          class="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
          aria-label="Export session"
          title="Download as JSON"
          onclick={onExport}
          disabled={exporting}
        >
          ⇣
        </button>
        <button
          type="button"
          class="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
          aria-label="Copy session to clipboard"
          title={copiedSession ? 'Copied' : 'Copy session as markdown'}
          onclick={onCopySession}
          disabled={copiedSession}
        >
          {copiedSession ? '✓' : '⎘'}
        </button>
        <button
          type="button"
          class="text-xs hover:text-slate-300 {bulkMode ? 'text-emerald-400' : 'text-slate-500'}"
          aria-label="Toggle bulk select mode"
          aria-pressed={bulkMode}
          title={bulkMode ? 'Exit bulk select' : 'Bulk select messages'}
          onclick={onToggleBulk}
          data-testid="bulk-toggle"
        >
          {bulkMode ? '☑' : '☐'}
        </button>
        <button
          type="button"
          class="text-xs text-slate-500 hover:text-slate-300"
          aria-label="Merge this session into another"
          title="Merge this session into another"
          onclick={onOpenMerge}
          data-testid="merge-session"
        >
          ⇲
        </button>
        <button
          type="button"
          class="text-xs text-slate-500 hover:text-slate-300"
          aria-label="Analyze and reorg this session"
          title="Analyze & reorg — propose splits"
          onclick={onOpenAnalyze}
          data-testid="analyze-reorg"
        >
          ✂
        </button>
        <button
          type="button"
          class="text-xs hover:text-slate-300 {sessions.selected.closed_at
            ? 'text-emerald-400'
            : 'text-slate-500'}"
          aria-label={sessions.selected.closed_at ? 'Reopen session' : 'Close session'}
          aria-pressed={!!sessions.selected.closed_at}
          title={sessions.selected.closed_at ? 'Reopen session' : 'Close session'}
          onclick={onToggleClosed}
          data-testid="close-session"
        >
          ✓
        </button>
      {/if}
    </h1>
    <p class="text-xs font-mono truncate text-slate-500">
      {#if sessions.selected}
        {sessions.selected.model} · {sessions.selected.working_dir} ·
        {#if billing.showTokens}
          <!-- Subscription mode: flat-rate billing makes the dollar
               figure meaningless, so swap in the token aggregate from
               /sessions/{id}/tokens. No budget cap rendered because
               `max_budget_usd` is dollar-denominated; a future slice
               can add a token-denominated cap. -->
          <TokenMeter totals={tokenTotals} />
        {:else}
          <span class={pressureClass(conversation.totalCost, sessions.selected.max_budget_usd)}>
            spent ${conversation.totalCost.toFixed(4)}{sessions.selected.max_budget_usd != null
              ? ` / $${sessions.selected.max_budget_usd.toFixed(2)}`
              : ''}
          </span>
        {/if}
        {#if sessions.selected.message_count > 0}
          · {sessions.selected.message_count} msg{sessions.selected.message_count === 1
            ? ''
            : 's'}
        {/if}
        {#if conversation.contextUsage}
          · <ContextMeter context={conversation.contextUsage} />
        {/if}
      {:else}
        select or create a session to start
      {/if}
    </p>
    {#if sessions.selected && sessionTags.length > 0}
      <ul class="flex flex-wrap gap-1 mt-1.5" aria-label="Session tags">
        {#each sessionTags as tag (tag.id)}
          <li
            class="inline-flex items-center gap-1 rounded bg-slate-800 px-1.5 py-0.5
              text-[10px] font-mono text-slate-300"
            title={tag.default_working_dir || tag.default_model
              ? `defaults: ${tag.default_working_dir ?? ''} ${tag.default_model ?? ''}`.trim()
              : tag.name}
          >
            {#if tag.pinned}
              <span class="text-amber-400" aria-hidden="true">★</span>
            {/if}
            <span>{tag.name}</span>
          </li>
        {/each}
      </ul>
    {/if}
    {#if sessions.selected?.description}
      <!--
        Two-layer clamp. `line-clamp-3` is the nice path (3 lines + ellipsis
        via -webkit-line-clamp) and works in Chromium. Firefox supports the
        same property pair, but the `-webkit-box` display can lose the cascade
        on flex children + whitespace-pre-wrap, leaving the clamp inert and
        the full multi-paragraph plug eating half the viewport. The explicit
        `max-h-[3.75rem]` (3 × 1.25rem text-xs line-height) + `overflow-hidden`
        is the floor that hard-caps height regardless of -webkit-box state,
        so Firefox sees the same 3-line preview Chromium does.
      -->
      <p
        bind:this={descriptionEl}
        class="text-xs text-slate-400 mt-1 whitespace-pre-wrap break-words
          {descriptionExpanded ? '' : 'line-clamp-3 max-h-[3.75rem] overflow-hidden'}"
        data-testid="session-description"
        data-expanded={descriptionExpanded ? 'true' : 'false'}
      >
        {sessions.selected.description}
      </p>
      {#if descriptionOverflows}
        <button
          type="button"
          class="text-[10px] uppercase tracking-wider text-slate-500
            hover:text-slate-300 mt-0.5"
          onclick={() => (descriptionExpanded = !descriptionExpanded)}
          data-testid="description-toggle"
          aria-expanded={descriptionExpanded}
        >
          {descriptionExpanded ? '⌃ show less' : '⌄ show more'}
        </button>
      {/if}
    {/if}
  </div>
  <div class="flex items-center gap-2">
    <PermissionModeSelector />
    {#if conversation.streamingActive}
      {#if agent.stopPendingStartedAt === null}
        <button
          type="button"
          class="text-[10px] uppercase tracking-wider px-2 py-1 rounded
            bg-rose-900 text-rose-200 hover:bg-rose-800"
          onclick={() => agent.stop()}
          title="Stop the in-flight stream"
        >
          Stop
        </button>
      {:else}
        <StopUndoInline />
      {/if}
    {/if}
    <span
      class="text-[10px] uppercase tracking-wider px-2 py-1 rounded
        {agent.state === 'open'
          ? 'bg-emerald-900 text-emerald-300'
          : agent.state === 'connecting'
            ? 'bg-amber-900 text-amber-300'
            : 'bg-slate-800 text-slate-400'}"
    >
      {connectionLabel(agent.state, agent.reconnectDelayMs, agent.lastCloseCode)}
    </span>
  </div>
</header>
