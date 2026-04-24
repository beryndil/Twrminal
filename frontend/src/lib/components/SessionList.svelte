<script lang="ts">
  import { billing } from '$lib/stores/billing.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { sessionSelection } from '$lib/stores/session_selection.svelte';
  import { tags } from '$lib/stores/tags.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import { contextmenu } from '$lib/actions/contextmenu';
  import type { ContextTarget } from '$lib/context-menu/types';
  import NewSessionForm from '$lib/components/NewSessionForm.svelte';
  import Settings from '$lib/components/Settings.svelte';
  import SidebarSearch from '$lib/components/SidebarSearch.svelte';
  import TagFilterPanel from '$lib/components/TagFilterPanel.svelte';
  import TemplatePicker from '$lib/components/TemplatePicker.svelte';
  import SeverityShield from '$lib/components/icons/SeverityShield.svelte';
  import TagIcon from '$lib/components/icons/TagIcon.svelte';

  const CONFIRM_TIMEOUT_MS = 3_000;

  let showNewForm = $state(false);
  let showSettings = $state(false);

  let importInput: HTMLInputElement | undefined = $state();
  let importError = $state<string | null>(null);
  let importProgress = $state<{ done: number; total: number } | null>(null);
  let dragging = $state(false);

  let searchQuery = $state('');

  // Collapsed state for the bottom "Closed (N)" group. Local-only by
  // design — a per-browser sticky preference would be a separate
  // prefs-store addition; resetting to collapsed each page load keeps
  // the sidebar quiet on boot.
  let closedCollapsed = $state(true);

  // Bound to the scrollable <aside> below so the scroll-to-top effect
  // can pull the just-bumped selected session into view. Otherwise a
  // user who'd scrolled down loses sight of their session the moment
  // it bumps to index 0.
  let asideEl: HTMLElement | undefined = $state();
  // Baseline so the mount-time run of the effect (which reads the
  // current tick) doesn't fire a gratuitous scroll. Only real tick
  // increments from this point forward trigger the scroll.
  // `?.scrollTo?.` also shrugs off jsdom, which doesn't implement it.
  let lastSeenScrollTick = sessions.scrollTick;
  $effect(() => {
    const t = sessions.scrollTick;
    if (t === lastSeenScrollTick) return;
    lastSeenScrollTick = t;
    asideEl?.scrollTo?.({ top: 0, behavior: 'smooth' });
  });

  async function importOne(file: File): Promise<api.Session> {
    const text = await file.text();
    const payload = JSON.parse(text);
    return api.importSession(payload);
  }

  async function importFromFiles(files: File[]) {
    if (files.length === 0) return;
    importError = null;
    const failures: { name: string; error: string }[] = [];
    const created: api.Session[] = [];
    importProgress = { done: 0, total: files.length };
    for (const file of files) {
      try {
        created.push(await importOne(file));
      } catch (err) {
        failures.push({
          name: file.name,
          error: err instanceof Error ? err.message : String(err)
        });
      }
      importProgress = { done: created.length + failures.length, total: files.length };
    }
    importProgress = null;

    // Prepend everything that landed — last-imported ends up on top.
    if (created.length > 0) {
      const keep = sessions.list.filter((s) => !created.some((c) => c.id === s.id));
      sessions.list = [...created.reverse(), ...keep];
      const focus = created[0]; // the last one imported (after reverse)
      sessions.select(focus.id);
      await agent.connect(focus.id);
    }
    if (failures.length > 0) {
      importError = failures.map((f) => `${f.name}: ${f.error}`).join('; ');
    }
  }

  async function onImportFile(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (files.length > 0) await importFromFiles(files);
  }

  function hasFiles(e: DragEvent): boolean {
    return e.dataTransfer?.types.includes('Files') ?? false;
  }

  function onDragEnter(e: DragEvent) {
    if (hasFiles(e)) dragging = true;
  }
  function onDragOver(e: DragEvent) {
    // preventDefault so the browser allows a drop; without this the
    // drop event never fires.
    if (hasFiles(e)) e.preventDefault();
  }
  function onDragLeave(e: DragEvent) {
    // Only clear when leaving the aside entirely, not when crossing
    // into a child element (relatedTarget outside the current node).
    const related = e.relatedTarget as Node | null;
    if (!related || !(e.currentTarget as Node).contains(related)) {
      dragging = false;
    }
  }
  async function onDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length > 0) await importFromFiles(files);
  }

  const confirm = $state<{ id: string | null }>({ id: null });
  let confirmTimer: ReturnType<typeof setTimeout> | null = null;

  function clearConfirm() {
    if (confirmTimer !== null) {
      clearTimeout(confirmTimer);
      confirmTimer = null;
    }
    confirm.id = null;
  }

  const rename = $state<{ id: string | null; draft: string }>({ id: null, draft: '' });

  function startRename(e: MouseEvent, session: { id: string; title: string | null; model: string }) {
    e.stopPropagation();
    rename.id = session.id;
    rename.draft = session.title ?? '';
  }

  async function commitRename() {
    if (rename.id === null) return;
    const id = rename.id;
    const draft = rename.draft.trim();
    rename.id = null;
    rename.draft = '';
    await sessions.update(id, { title: draft === '' ? null : draft });
  }

  function cancelRename() {
    rename.id = null;
    rename.draft = '';
  }

  function onRenameKey(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitRename();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelRename();
    }
  }

  // Boot (auth + session refresh) is owned by +page.svelte so the auth
  // gate can block API calls until a token is supplied.

  // Re-fetch the session list whenever any filter axis changes.
  // Initial boot in +page.svelte happens before the first effect
  // settles, so this only fires on subsequent filter edits. The key
  // encodes both axes — general-tag selection and severity selection —
  // so adding/removing either triggers a refresh without a user also
  // having to touch the other axis. General-tag combination is always
  // OR now (v0.7.4), so there's no separate `mode` component to key
  // off of.
  let filterKey = $derived(
    `${tags.selected.join(',')}|${tags.selectedSeverity.join(',')}`
  );
  let lastAppliedKey = '';
  $effect(() => {
    const key = filterKey;
    if (key === lastAppliedKey) return;
    lastAppliedKey = key;
    sessions.refresh(tags.filter);
  });

  // v0.7.4: severity counts in the sidebar are scoped to the current
  // general-tag selection, so each change to `tags.selected` needs
  // a tag refresh to pull the updated counts from the server.
  // Severity selection doesn't feed into this — severity counts are
  // independent of severity selection (the count would otherwise
  // collapse to the sum of selected severities, which is
  // meaningless). Keyed off the general selection only to avoid a
  // wasteful refresh when severity alone toggles.
  let generalSelectionKey = $derived(tags.selected.join(','));
  let lastGeneralKey = '';
  $effect(() => {
    const key = generalSelectionKey;
    if (key === lastGeneralKey) return;
    lastGeneralKey = key;
    void tags.refresh();
  });

  /** Ordered ids of every session currently rendered in the sidebar —
   * `openList` first, then `closedList`. Used as the range-selection
   * axis for Shift-click so anchors span the visual order the user
   * sees. Re-derived every tick so filter changes keep the range in
   * sync. */
  let orderedVisibleIds = $derived([
    ...sessions.openList.map((s) => s.id),
    ...sessions.closedList.map((s) => s.id)
  ]);

  /** Resolve the context-menu target for a right-clicked session row.
   * If the row is part of the active multi-selection, dispatch the
   * aggregate `multi_select` target — otherwise stay on the per-session
   * menu. Rows right-clicked while a disjoint selection exists keep
   * their single-session menu (the selection belongs to other rows). */
  function rowTarget(id: string): ContextTarget {
    if (sessionSelection.hasSelection && sessionSelection.ids.has(id)) {
      return { type: 'multi_select', ids: [...sessionSelection.ids] };
    }
    return { type: 'session', id };
  }

  async function onSelect(id: string, e: MouseEvent) {
    // Cmd/Ctrl+click toggles membership without touching the navigated
    // session. The sidebar's focused session stays put so Daisy can
    // keep reading while she composes a batch.
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      sessionSelection.toggle(id);
      return;
    }
    // Shift+click grows the selection inclusively from the anchor.
    // Fall back to `toggle` inside selectRange when no anchor is set.
    if (e.shiftKey) {
      e.preventDefault();
      sessionSelection.selectRange(id, orderedVisibleIds);
      return;
    }
    // Plain click: collapse any multi-selection, then navigate.
    if (sessionSelection.hasSelection) sessionSelection.clear();
    sessions.select(id);
    // Clear the "finished but unviewed" amber dot for this session.
    // Fire-and-forget: the optimistic path in `markViewed` updates the
    // local row synchronously so the dot goes away immediately.
    void sessions.markViewed(id);
    // v0.5.2: both chat and checklist sessions run an agent loop.
    // Checklist sessions host an embedded chat panel in ChecklistView
    // and the backend's `checklist_overview` prompt layer injects the
    // list's state into every turn.
    await agent.connect(id);
  }

  async function onDelete(e: MouseEvent, id: string) {
    e.stopPropagation();
    if (confirm.id !== id) {
      confirm.id = id;
      if (confirmTimer !== null) clearTimeout(confirmTimer);
      confirmTimer = setTimeout(clearConfirm, CONFIRM_TIMEOUT_MS);
      return;
    }
    clearConfirm();
    if (agent.sessionId === id) agent.close();
    await sessions.remove(id);
  }

  /** True when the server-side runner for this session has a turn in
   * flight. The sidebar badge uses this so Daisy can see at a glance
   * which sessions are still working after she's walked away. */
  function isRunning(id: string): boolean {
    return sessions.running.has(id);
  }

  /** True when the session has produced output since the user last
   * looked at it — drives the amber "finished but unviewed" dot.
   * Suppressed while the session is actively running so the green
   * ping owns the slot during live work. */
  function isUnviewed(session: api.Session): boolean {
    if (isRunning(session.id)) return false;
    if (!session.last_completed_at) return false;
    if (!session.last_viewed_at) return true;
    return session.last_completed_at > session.last_viewed_at;
  }

  function formatTimestamp(ts: string): string {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  }

  function costClass(session: api.Session): string {
    const cap = session.max_budget_usd;
    if (cap == null || cap <= 0) return 'text-slate-600';
    const ratio = session.total_cost_usd / cap;
    if (ratio >= 1) return 'text-rose-400';
    if (ratio >= 0.8) return 'text-amber-400';
    return 'text-slate-600';
  }

  /** Resolve a session's `tag_ids` into the in-memory tag rows so the
   * medallion row can pull color + group without a per-row fetch.
   * Returns `null` for any id the tag store hasn't loaded yet —
   * filtered out at the callsite. */
  function tagsFor(session: api.Session): api.Tag[] {
    const byId = new Map(tags.list.map((t) => [t.id, t]));
    const ids = session.tag_ids ?? [];
    const out: api.Tag[] = [];
    for (const id of ids) {
      const hit = byId.get(id);
      if (hit) out.push(hit);
    }
    return out;
  }

  /** Split a session's tag list into the severity slot (one tag or
   * null) and the ordered general-tag list. Severity lookup is by
   * `tag_group` — the exactly-one invariant is enforced server-side
   * so we don't re-check here. */
  function medallionData(session: api.Session): {
    severity: api.Tag | null;
    general: api.Tag[];
  } {
    const resolved = tagsFor(session);
    const severity = resolved.find((t) => t.tag_group === 'severity') ?? null;
    const general = resolved.filter((t) => t.tag_group !== 'severity');
    return { severity, general };
  }
</script>

<Settings bind:open={showSettings} />

<aside
  bind:this={asideEl}
  class="relative h-full bg-slate-900 p-2 overflow-y-auto border-r border-slate-800
    flex flex-col gap-2 {dragging ? 'ring-2 ring-emerald-500/60 ring-inset' : ''}"
  ondragenter={onDragEnter}
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
>
  <div class="flex items-center justify-between gap-2">
    <h2 class="text-xs uppercase tracking-wider text-slate-400">Sessions</h2>
    <div class="flex items-center gap-1">
      <button
        type="button"
        class="text-[11px] rounded bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5"
        aria-label="Import session from JSON"
        title="Import a session.json file"
        onclick={() => importInput?.click()}
      >
        ⇡
      </button>
      <input
        type="file"
        accept="application/json,.json"
        multiple
        class="hidden"
        bind:this={importInput}
        onchange={onImportFile}
      />
      <TemplatePicker />
      <a
        href="/vault"
        class="text-[11px] rounded bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5"
        aria-label="Open vault (plans + TODOs)"
        title="Open vault — browse plans and TODO.md files"
        data-testid="vault-link"
      >
        📚
      </a>
      <button
        type="button"
        class="text-[11px] rounded bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5"
        aria-label="Open settings"
        onclick={() => (showSettings = true)}
      >
        ⚙
      </button>
      <button
        type="button"
        class="text-[11px] rounded bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5"
        onclick={() => (showNewForm = !showNewForm)}
        aria-label="Toggle new session form"
      >
        {showNewForm ? 'Cancel' : '+ New'}
      </button>
    </div>
  </div>

  {#if dragging}
    <div
      class="pointer-events-none absolute inset-2 rounded border-2 border-dashed
        border-emerald-500/70 bg-slate-950/60 flex items-center justify-center z-10"
    >
      <p class="text-sm text-emerald-300">Drop session JSON to import</p>
    </div>
  {/if}

  <SidebarSearch bind:query={searchQuery} />

  <NewSessionForm bind:open={showNewForm} />

  {#if sessions.error}
    <p class="text-xs text-rose-400">{sessions.error}</p>
  {/if}
  {#if importProgress}
    <p class="text-xs text-emerald-300">
      Importing {importProgress.done} of {importProgress.total}…
    </p>
  {/if}
  {#if importError}
    <p class="text-xs text-rose-400">import: {importError}</p>
  {/if}

  {#if !searchQuery.trim()}
    <TagFilterPanel />
  {/if}

  {#snippet sessionRow(session: api.Session)}
    {@const medals = medallionData(session)}
    {@const isBulkSelected = sessionSelection.ids.has(session.id)}
    <li
      class="group flex items-stretch gap-1 rounded hover:bg-slate-800 {sessions.selectedId ===
      session.id
        ? 'bg-slate-800'
        : ''} {isBulkSelected ? 'ring-1 ring-emerald-500/60 bg-slate-800/80' : ''}"
      use:contextmenu={{ target: rowTarget(session.id) }}
      data-multi-selected={isBulkSelected ? 'true' : 'false'}
    >
      <button
        type="button"
        class="flex-1 min-w-0 text-left px-2 py-1 rounded-l"
        onclick={(e) => onSelect(session.id, e)}
        ondblclick={(e) => startRename(e, session)}
      >
        {#if rename.id === session.id}
          <!-- svelte-ignore a11y_autofocus -->
          <input
            type="text"
            class="w-full bg-slate-950 rounded px-1 py-0.5 text-xs
              border border-slate-700 focus:outline-none focus:border-emerald-600"
            bind:value={rename.draft}
            onkeydown={onRenameKey}
            onblur={commitRename}
            onclick={(e) => e.stopPropagation()}
            autofocus
            placeholder="Session title"
          />
        {:else}
          <!-- Three-row grid: col 1 reserves space for the activity
               indicator so rows 2–3 indent cleanly under the title.
               Row 1: [indicator | title … severity shield].
               Row 2: [—        | general tag icons + working_dir].
               Row 3: [—        | updated_at … cost]. -->
          <div
            class="grid grid-cols-[0.75rem_1fr] gap-x-1 text-xs"
            title="Double-click to rename"
          >
            <!-- Row 1, Col 1: activity indicator slot. Width is
                 always reserved so titles align whether or not an
                 indicator is showing. -->
            <div class="row-start-1 col-start-1 flex items-center justify-center">
              {#if isRunning(session.id)}
                <!-- Live-run indicator: emerald ping + solid dot. -->
                <span
                  class="relative inline-flex h-1.5 w-1.5 shrink-0"
                  aria-label="Agent is working"
                  title="Agent is working — you can switch away and come back"
                >
                  <span
                    class="absolute inline-flex h-full w-full rounded-full
                      bg-emerald-400 opacity-60 animate-ping"
                  ></span>
                  <span
                    class="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500"
                  ></span>
                </span>
              {:else if isUnviewed(session)}
                <!-- Finished-but-unviewed indicator. -->
                <span
                  class="relative inline-flex h-1.5 w-1.5 shrink-0"
                  aria-label="Session finished — unread"
                  title="Session finished — unread since last view"
                  data-testid="unviewed-dot"
                >
                  <span
                    class="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-400"
                  ></span>
                </span>
              {/if}
            </div>

            <!-- Row 1, Col 2: title with severity shield pinned to
                 the right edge. The checklist marker stays inline
                 with the title so ☑ still reads as a type badge. -->
            <div class="row-start-1 col-start-2 flex items-center gap-1 min-w-0">
              {#if session.kind === 'checklist'}
                <span
                  class="text-slate-500 shrink-0"
                  aria-label="Checklist session"
                  title="Checklist session">☑</span
                >
              {/if}
              <span class="min-w-0 truncate flex-1">
                {session.title ?? session.model}
              </span>
              <SeverityShield
                color={medals.severity?.color ?? null}
                title={medals.severity?.name ?? 'No severity'}
                size={11}
              />
            </div>

            <!-- Row 2, Col 2: general-group tag icons ("what project
                 are we on") followed by the working_dir path. -->
            <div
              class="row-start-2 col-start-2 flex items-center gap-1 min-w-0"
              data-testid="medallion-row"
            >
              {#each medals.general as tag (tag.id)}
                <TagIcon color={tag.color} title={tag.name} size={11} />
              {/each}
              <span class="text-[10px] text-slate-500 font-mono truncate min-w-0">
                {session.working_dir}
              </span>
            </div>

            <!-- Row 3, Col 2: timestamp + optional cost. -->
            <div
              class="row-start-3 col-start-2 text-[10px] flex
                justify-between items-baseline gap-2"
            >
              <span class="text-slate-600">
                {formatTimestamp(session.updated_at)}
              </span>
              {#if !billing.showTokens && session.total_cost_usd > 0}
                <span class="font-mono {costClass(session)}">
                  ${session.total_cost_usd.toFixed(4)}
                </span>
              {/if}
            </div>
          </div>
        {/if}
      </button>
      <button
        type="button"
        class="px-1.5 text-[11px] transition {confirm.id === session.id
          ? 'text-rose-400 font-medium'
          : 'text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100'}"
        aria-label={confirm.id === session.id
          ? 'Confirm delete session'
          : 'Delete session'}
        onclick={(e) => onDelete(e, session.id)}
      >
        {confirm.id === session.id ? 'Confirm?' : '✕'}
      </button>
    </li>
  {/snippet}

  {#if searchQuery.trim()}
    <!-- SidebarSearch renders its own results list above. -->
  {:else if sessions.loading && sessions.list.length === 0}
    <p class="text-slate-500 text-sm">Loading…</p>
  {:else if sessions.list.length === 0}
    <p class="text-slate-500 text-sm">No sessions yet.</p>
  {:else}
    {#if sessions.openList.length > 0}
      <ul class="flex flex-col gap-1">
        {#each sessions.openList as session (session.id)}
          {@render sessionRow(session)}
        {/each}
      </ul>
    {:else}
      <p class="text-slate-500 text-sm">No open sessions.</p>
    {/if}

    {#if sessionSelection.hasSelection}
      <!-- Selection footer: sticky reminder that bulk mode is active.
           The real bulk ops fire from the right-click menu on any
           selected row (dispatches the `multi_select` target). -->
      <div
        class="mt-2 border-t border-emerald-700/40 pt-2 flex items-center
          justify-between gap-2 text-xs"
        data-testid="session-bulk-bar"
      >
        <span class="text-emerald-300">
          {sessionSelection.size} selected
        </span>
        <span class="text-slate-500">Right-click for actions</span>
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-2 py-0.5 text-[11px]
            text-slate-300"
          onclick={() => sessionSelection.clear()}
          data-testid="session-bulk-clear"
        >
          Clear
        </button>
      </div>
    {/if}

    {#if sessions.closedList.length > 0}
      <div class="mt-2 border-t border-slate-800 pt-1">
        <button
          type="button"
          class="w-full flex items-center justify-between px-1 py-0.5 text-[11px]
            uppercase tracking-wider text-slate-400 hover:text-slate-200"
          aria-expanded={!closedCollapsed}
          aria-controls="closed-sessions-group"
          onclick={() => (closedCollapsed = !closedCollapsed)}
          data-testid="closed-group-toggle"
        >
          <span>Closed ({sessions.closedList.length})</span>
          <span aria-hidden="true">{closedCollapsed ? '▸' : '▾'}</span>
        </button>
        {#if !closedCollapsed}
          <ul
            id="closed-sessions-group"
            class="flex flex-col gap-0.5 mt-1"
            data-testid="closed-sessions-list"
          >
            {#each sessions.closedList as session (session.id)}
              {@render sessionRow(session)}
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  {/if}
</aside>
