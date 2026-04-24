<script lang="ts">
  /**
   * Read-only browser for the on-disk planning surface. Lists every
   * markdown doc aggregated under `settings.vault.plan_roots` +
   * `settings.vault.todo_globs` (see `routes_vault.py`) and renders
   * the selected doc with the same `marked + shiki` pipeline used for
   * chat turns.
   *
   * Why a dedicated route instead of a modal on the main page:
   *  1. Deep-linkable: `/vault?path=…` or `/vault?slug=…` lets a
   *     session row link to its matching plan without bolting a
   *     global modal into the existing layout.
   *  2. The main page is already heavy (Conversation + SessionList +
   *     Inspector + command palette) — piling a doc browser into
   *     `+page.svelte` would compound that complexity.
   *
   * Scope cuts (intentional, documented in the ship plan):
   *  - No editing. TODO.md files are the source of truth for multiple
   *    tools and editing them from a browser would race the "append
   *    in the moment" rule.
   *  - No live updates. Index is fetched on route entry and on window
   *    focus; a watchfiles-driven WS can land in a later slice if
   *    files change often enough mid-browse to matter.
   *  - No session cross-link yet. Plan slugs match session slugs by
   *    convention — a later slice can wire an "Open session" button
   *    once we want the dependency on the sessions store.
   */
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import * as api from '$lib/api';
  import { renderMarkdown } from '$lib/render';

  let index = $state<api.VaultIndex | null>(null);
  let indexError = $state<string | null>(null);
  let loadingIndex = $state(false);
  let activeTab = $state<'plans' | 'todos'>('plans');
  let filterQuery = $state('');

  // Selected doc is tracked by path because `slug` can collide across
  // kinds (e.g. every nested project has a `TODO.md` stem). Path is
  // the only index identity that survives the `plans` ↔ `todos` tab
  // swap and the search-hit jump.
  let selectedPath = $state<string | null>(null);
  let doc = $state<api.VaultDoc | null>(null);
  let docError = $state<string | null>(null);
  let loadingDoc = $state(false);

  let searchQuery = $state('');
  let searchHits = $state<api.VaultSearchHit[] | null>(null);
  let searchTruncated = $state(false);
  let searchError = $state<string | null>(null);
  let loadingSearch = $state(false);

  const currentList = $derived<api.VaultEntry[]>(
    index ? (activeTab === 'plans' ? index.plans : index.todos) : []
  );
  const filteredList = $derived.by(() => {
    const needle = filterQuery.trim().toLowerCase();
    if (!needle) return currentList;
    return currentList.filter(
      (e) =>
        e.slug.toLowerCase().includes(needle) ||
        (e.title ?? '').toLowerCase().includes(needle) ||
        e.path.toLowerCase().includes(needle)
    );
  });
  const renderedBody = $derived(doc ? renderMarkdown(doc.body) : '');

  async function loadIndex(): Promise<void> {
    loadingIndex = true;
    indexError = null;
    try {
      index = await api.fetchVaultIndex();
    } catch (e) {
      indexError = e instanceof Error ? e.message : String(e);
    } finally {
      loadingIndex = false;
    }
  }

  async function loadDoc(path: string): Promise<void> {
    loadingDoc = true;
    docError = null;
    try {
      doc = await api.fetchVaultDoc(path);
    } catch (e) {
      docError = e instanceof Error ? e.message : String(e);
      doc = null;
    } finally {
      loadingDoc = false;
    }
  }

  function selectEntry(entry: api.VaultEntry): void {
    selectedPath = entry.path;
    // Switching tab is implicit when the caller hands us an entry
    // from the other bucket — a search hit can jump across tabs.
    activeTab = entry.kind === 'plan' ? 'plans' : 'todos';
    void loadDoc(entry.path);
  }

  async function runSearch(): Promise<void> {
    const q = searchQuery.trim();
    if (!q) {
      searchHits = null;
      searchTruncated = false;
      return;
    }
    loadingSearch = true;
    searchError = null;
    try {
      const result = await api.searchVault(q);
      searchHits = result.hits;
      searchTruncated = result.truncated;
    } catch (e) {
      searchError = e instanceof Error ? e.message : String(e);
      searchHits = null;
    } finally {
      loadingSearch = false;
    }
  }

  function clearSearch(): void {
    searchQuery = '';
    searchHits = null;
    searchTruncated = false;
    searchError = null;
  }

  function formatMtime(ts: number): string {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  // Pick up `?path=/abs/path` for session→plan deep-links, and
  // `?tab=todos` so a link can land on the TODOs bucket directly.
  function applyQueryParams(): void {
    const search = $page.url.searchParams;
    const tab = search.get('tab');
    if (tab === 'plans' || tab === 'todos') activeTab = tab;
    const wanted = search.get('path');
    if (wanted && wanted !== selectedPath) {
      selectedPath = wanted;
      void loadDoc(wanted);
    }
  }

  onMount(() => {
    void loadIndex();
    applyQueryParams();
    function onVisible(): void {
      if (document.visibilityState === 'visible') void loadIndex();
    }
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  });
</script>

<svelte:head>
  <title>Vault — Bearings</title>
</svelte:head>

<div class="flex h-screen flex-col bg-slate-950 text-slate-100">
  <header class="flex items-center gap-4 border-b border-slate-800 px-6 py-3">
    <a
      href="/"
      class="rounded px-2 py-1 text-sm text-slate-400 hover:bg-slate-800 hover:text-slate-100"
    >
      ← Bearings
    </a>
    <h1 class="text-lg font-semibold text-emerald-400">Vault</h1>
    <nav class="flex gap-1">
      <button
        type="button"
        class="rounded px-3 py-1 text-sm"
        class:bg-slate-800={activeTab === 'plans'}
        class:text-emerald-300={activeTab === 'plans'}
        class:text-slate-400={activeTab !== 'plans'}
        onclick={() => (activeTab = 'plans')}
      >
        Plans ({index?.plans.length ?? 0})
      </button>
      <button
        type="button"
        class="rounded px-3 py-1 text-sm"
        class:bg-slate-800={activeTab === 'todos'}
        class:text-emerald-300={activeTab === 'todos'}
        class:text-slate-400={activeTab !== 'todos'}
        onclick={() => (activeTab = 'todos')}
      >
        TODOs ({index?.todos.length ?? 0})
      </button>
    </nav>
    <form
      class="ml-auto flex items-center gap-2"
      onsubmit={(ev) => {
        ev.preventDefault();
        void runSearch();
      }}
    >
      <input
        type="search"
        placeholder="Search across all docs"
        bind:value={searchQuery}
        class="w-72 rounded border border-slate-700 bg-slate-900 px-3 py-1 text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none"
      />
      <button
        type="submit"
        class="rounded bg-emerald-600 px-3 py-1 text-sm font-medium text-slate-950 hover:bg-emerald-500 disabled:opacity-50"
        disabled={loadingSearch || !searchQuery.trim()}
      >
        Search
      </button>
      {#if searchHits !== null}
        <button
          type="button"
          class="rounded border border-slate-700 px-3 py-1 text-sm text-slate-400 hover:bg-slate-800"
          onclick={clearSearch}
        >
          Clear
        </button>
      {/if}
    </form>
  </header>

  <div class="flex min-h-0 flex-1">
    <aside
      class="flex w-80 shrink-0 flex-col border-r border-slate-800 bg-slate-950"
    >
      <div class="border-b border-slate-800 px-4 py-2">
        <input
          type="text"
          placeholder="Filter this list…"
          bind:value={filterQuery}
          class="w-full rounded border border-slate-800 bg-slate-900 px-2 py-1 text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none"
        />
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto">
        {#if loadingIndex && !index}
          <p class="px-4 py-6 text-sm text-slate-500">Loading…</p>
        {:else if indexError}
          <p class="px-4 py-6 text-sm text-rose-400">{indexError}</p>
        {:else if searchHits !== null}
          <section class="px-2 py-2">
            <header class="px-2 pb-2 text-xs uppercase text-slate-500">
              {searchHits.length} hit{searchHits.length === 1 ? '' : 's'}
              {#if searchTruncated}
                <span class="text-amber-400">(truncated — narrow query)</span>
              {/if}
            </header>
            {#if searchError}
              <p class="px-2 py-2 text-sm text-rose-400">{searchError}</p>
            {/if}
            <ul class="space-y-1">
              {#each searchHits as hit (hit.path + ':' + hit.line)}
                {@const entry = [...(index?.plans ?? []), ...(index?.todos ?? [])].find(
                  (e) => e.path === hit.path
                )}
                <li>
                  <button
                    type="button"
                    class="w-full rounded px-2 py-1 text-left text-sm hover:bg-slate-900"
                    class:bg-slate-900={selectedPath === hit.path}
                    onclick={() => entry && selectEntry(entry)}
                    disabled={!entry}
                  >
                    <div class="truncate text-slate-200">
                      {entry?.title ?? entry?.slug ?? hit.path.split('/').pop()}
                    </div>
                    <div class="truncate text-xs text-slate-500">
                      line {hit.line}: {hit.snippet}
                    </div>
                  </button>
                </li>
              {/each}
            </ul>
          </section>
        {:else if filteredList.length === 0}
          <p class="px-4 py-6 text-sm text-slate-500">
            {currentList.length === 0
              ? 'No docs in this bucket.'
              : 'No matches for the filter.'}
          </p>
        {:else}
          <ul class="space-y-0.5 px-2 py-2">
            {#each filteredList as entry (entry.path)}
              <li>
                <button
                  type="button"
                  class="block w-full rounded px-2 py-1.5 text-left hover:bg-slate-900"
                  class:bg-slate-900={selectedPath === entry.path}
                  onclick={() => selectEntry(entry)}
                >
                  <div class="truncate text-sm text-slate-200">
                    {entry.title ?? entry.slug}
                  </div>
                  <div class="truncate text-xs text-slate-500">
                    {formatMtime(entry.mtime)} · {formatSize(entry.size)}
                  </div>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    </aside>

    <main class="min-w-0 flex-1 overflow-y-auto bg-slate-900">
      {#if doc}
        <article class="mx-auto max-w-4xl px-8 py-6">
          <header class="mb-6 border-b border-slate-800 pb-4">
            <h2 class="text-2xl font-semibold text-slate-100">
              {doc.title ?? doc.slug}
            </h2>
            <div class="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
              <span class="rounded bg-slate-800 px-2 py-0.5 font-mono">
                {doc.kind}
              </span>
              <span>{formatMtime(doc.mtime)}</span>
              <span>{formatSize(doc.size)}</span>
              <span class="font-mono text-slate-600">{doc.path}</span>
            </div>
          </header>
          <!-- renderMarkdown DOMPurifies before returning; the HTML
               here is trusted output from the shared renderer. -->
          <div class="prose prose-invert max-w-none">
            {@html renderedBody}
          </div>
        </article>
      {:else if loadingDoc}
        <p class="px-8 py-6 text-sm text-slate-500">Loading doc…</p>
      {:else if docError}
        <p class="px-8 py-6 text-sm text-rose-400">{docError}</p>
      {:else}
        <div class="flex h-full items-center justify-center text-slate-500">
          <p class="text-sm">Pick a doc from the sidebar to read it.</p>
        </div>
      {/if}
    </main>
  </div>
</div>
