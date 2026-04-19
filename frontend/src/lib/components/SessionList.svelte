<script lang="ts">
  import { onMount } from 'svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { prefs } from '$lib/stores/prefs.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import { parseBudget } from '$lib/utils/budget';
  import { highlightText } from '$lib/utils/highlight';
  import Settings from '$lib/components/Settings.svelte';

  const CONFIRM_TIMEOUT_MS = 3_000;
  const SEARCH_DEBOUNCE_MS = 200;

  let showNewForm = $state(false);
  let showSettings = $state(false);
  let newWorkingDir = $state('');
  let newModel = $state('claude-sonnet-4-6');
  let newTitle = $state('');
  let newBudget = $state('');
  let submitting = $state(false);

  let searchQuery = $state('');
  let searchResults = $state<api.SearchHit[]>([]);
  let searchError = $state<string | null>(null);
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  function runSearch(q: string) {
    if (searchTimer !== null) clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      if (!q.trim()) {
        searchResults = [];
        searchError = null;
        return;
      }
      try {
        searchResults = await api.searchHistory(q.trim());
        searchError = null;
      } catch (e) {
        searchError = e instanceof Error ? e.message : String(e);
      }
    }, SEARCH_DEBOUNCE_MS);
  }

  $effect(() => {
    runSearch(searchQuery);
  });

  async function onPickResult(sid: string) {
    const q = searchQuery.trim();
    searchQuery = '';
    searchResults = [];
    sessions.select(sid);
    await agent.connect(sid);
    // agent.connect → conversation.load clears highlightQuery via
    // reset(); set it *after* the load so rendered messages pick it up.
    conversation.highlightQuery = q;
  }

  function toggleNewForm() {
    if (showNewForm) {
      showNewForm = false;
      return;
    }
    // Seed from prefs every time the form re-opens; user edits during
    // the open session stay put.
    newWorkingDir = prefs.defaultWorkingDir || newWorkingDir;
    newModel = prefs.defaultModel || newModel;
    showNewForm = true;
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

  async function onCreate() {
    submitting = true;
    const created = await sessions.create({
      working_dir: newWorkingDir.trim() || prefs.defaultWorkingDir || '/tmp',
      model: newModel.trim() || prefs.defaultModel || 'claude-sonnet-4-6',
      title: newTitle.trim() || null,
      max_budget_usd: parseBudget(newBudget)
    });
    submitting = false;
    if (created) {
      showNewForm = false;
      newWorkingDir = '';
      newTitle = '';
      newBudget = '';
      await agent.connect(created.id);
    }
  }

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
</script>

<Settings bind:open={showSettings} />

<aside class="bg-slate-900 p-4 overflow-y-auto border-r border-slate-800 flex flex-col gap-3">
  <div class="flex items-center justify-between gap-2">
    <h2 class="text-sm uppercase tracking-wider text-slate-400">Sessions</h2>
    <div class="flex items-center gap-1">
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
        onclick={toggleNewForm}
        aria-label="Toggle new session form"
      >
        {showNewForm ? 'Cancel' : '+ New'}
      </button>
    </div>
  </div>

  <input
    type="search"
    placeholder="Search messages…"
    class="rounded bg-slate-950 border border-slate-800 px-2 py-1.5 text-sm
      focus:outline-none focus:border-slate-600"
    bind:value={searchQuery}
  />

  {#if showNewForm}
    <form
      class="flex flex-col gap-2 rounded bg-slate-800/60 p-3"
      onsubmit={(e) => {
        e.preventDefault();
        onCreate();
      }}
    >
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Working dir</span>
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm"
          placeholder="/home/..."
          bind:value={newWorkingDir}
        />
      </label>
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Model</span>
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm font-mono"
          bind:value={newModel}
        />
      </label>
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Title <span class="text-slate-600">(optional)</span></span>
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm"
          bind:value={newTitle}
        />
      </label>
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400"
          >Budget USD <span class="text-slate-600">(optional)</span></span
        >
        <input
          type="number"
          inputmode="decimal"
          step="0.01"
          min="0"
          placeholder="no cap"
          class="rounded bg-slate-950 px-2 py-1 text-sm font-mono"
          bind:value={newBudget}
        />
      </label>
      <button
        type="submit"
        class="rounded bg-emerald-600 hover:bg-emerald-500 px-2 py-1 text-sm mt-1 disabled:opacity-50"
        disabled={submitting}
      >
        {submitting ? 'Creating…' : 'Create session'}
      </button>
    </form>
  {/if}

  {#if sessions.error}
    <p class="text-xs text-rose-400">{sessions.error}</p>
  {/if}

  {#if searchQuery.trim()}
    {#if searchError}
      <p class="text-xs text-rose-400">{searchError}</p>
    {:else if searchResults.length === 0}
      <p class="text-slate-500 text-sm">No matches.</p>
    {:else}
      <ul class="flex flex-col gap-1">
        {#each searchResults as hit (hit.message_id)}
          <li>
            <button
              type="button"
              class="w-full text-left rounded bg-slate-800/40 hover:bg-slate-800 px-2 py-2"
              onclick={() => onPickResult(hit.session_id)}
            >
              <div class="flex items-baseline justify-between gap-2">
                <span class="text-sm truncate">
                  {hit.session_title ?? hit.model}
                </span>
                <span class="text-[10px] uppercase text-slate-500">{hit.role}</span>
              </div>
              <div class="text-[11px] text-slate-300 mt-0.5 line-clamp-2 snippet">
                {@html highlightText(hit.snippet, searchQuery.trim())}
              </div>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
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
            <div class="text-[10px] text-slate-600">
              {formatTimestamp(session.created_at)}
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

<style>
  .snippet :global(mark) {
    background-color: rgb(234 179 8 / 0.35);
    color: rgb(253 224 71);
    border-radius: 0.125rem;
    padding: 0 0.125rem;
  }
</style>
