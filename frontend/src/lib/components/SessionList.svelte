<script lang="ts">
  import { sessions } from '$lib/stores/sessions.svelte';
  import { tags } from '$lib/stores/tags.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import NewSessionForm from '$lib/components/NewSessionForm.svelte';
  import Settings from '$lib/components/Settings.svelte';
  import SidebarSearch from '$lib/components/SidebarSearch.svelte';
  import TagFilterPanel from '$lib/components/TagFilterPanel.svelte';

  const CONFIRM_TIMEOUT_MS = 3_000;

  let showNewForm = $state(false);
  let showSettings = $state(false);

  let importInput: HTMLInputElement | undefined = $state();
  let importError = $state<string | null>(null);
  let importProgress = $state<{ done: number; total: number } | null>(null);
  let dragging = $state(false);

  let searchQuery = $state('');

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

  // Re-fetch the session list whenever the tag filter changes. Initial
  // boot in +page.svelte happens before the first effect settles, so
  // this only fires on subsequent filter edits.
  let filterKey = $derived(`${tags.selected.join(',')}|${tags.mode}`);
  let lastAppliedKey = '';
  $effect(() => {
    const key = filterKey;
    if (key === lastAppliedKey) return;
    lastAppliedKey = key;
    sessions.refresh(tags.filter);
  });

  async function onSelect(id: string) {
    sessions.select(id);
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
</script>

<Settings bind:open={showSettings} />

<aside
  class="relative bg-slate-900 p-4 overflow-y-auto border-r border-slate-800
    flex flex-col gap-3 {dragging ? 'ring-2 ring-emerald-500/60 ring-inset' : ''}"
  ondragenter={onDragEnter}
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
>
  <div class="flex items-center justify-between gap-2">
    <h2 class="text-sm uppercase tracking-wider text-slate-400">Sessions</h2>
    <div class="flex items-center gap-1">
      <button
        type="button"
        class="text-xs rounded bg-slate-800 hover:bg-slate-700 px-2 py-1"
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
      <button
        type="button"
        class="text-xs rounded bg-slate-800 hover:bg-slate-700 px-2 py-1"
        aria-label="Open settings"
        onclick={() => (showSettings = true)}
      >
        ⚙
      </button>
      <button
        type="button"
        class="text-xs rounded bg-slate-800 hover:bg-slate-700 px-2 py-1"
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

  {#if searchQuery.trim()}
    <!-- SidebarSearch renders its own results list above. -->
  {:else if sessions.loading && sessions.list.length === 0}
    <p class="text-slate-500 text-sm">Loading…</p>
  {:else if sessions.list.length === 0}
    <p class="text-slate-500 text-sm">No sessions yet.</p>
  {:else}
    <ul class="flex flex-col gap-1">
      {#each sessions.list as session (session.id)}
        <li
          class="group flex items-stretch gap-1 rounded hover:bg-slate-800 {sessions.selectedId ===
          session.id
            ? 'bg-slate-800'
            : ''}"
        >
          <button
            type="button"
            class="flex-1 min-w-0 text-left px-2 py-2 rounded-l"
            onclick={() => onSelect(session.id)}
            ondblclick={(e) => startRename(e, session)}
          >
            {#if rename.id === session.id}
              <!-- svelte-ignore a11y_autofocus -->
              <input
                type="text"
                class="w-full bg-slate-950 rounded px-1 py-0.5 text-sm
                  border border-slate-700 focus:outline-none focus:border-emerald-600"
                bind:value={rename.draft}
                onkeydown={onRenameKey}
                onblur={commitRename}
                onclick={(e) => e.stopPropagation()}
                autofocus
                placeholder="Session title"
              />
            {:else}
              <div class="text-sm truncate" title="Double-click to rename">
                {session.title ?? session.model}
              </div>
            {/if}
            <div class="text-[10px] text-slate-500 font-mono truncate">
              {session.working_dir}
            </div>
            <div class="text-[10px] flex justify-between items-baseline gap-2">
              <span class="text-slate-600">
                {formatTimestamp(session.updated_at)}
              </span>
              {#if session.total_cost_usd > 0}
                <span class="font-mono {costClass(session)}">
                  ${session.total_cost_usd.toFixed(4)}
                </span>
              {/if}
            </div>
          </button>
          <button
            type="button"
            class="px-2 text-xs transition {confirm.id === session.id
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
      {/each}
    </ul>
  {/if}
</aside>
