<script lang="ts">
  import { onMount } from 'svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { tags } from '$lib/stores/tags.svelte';
  import { prefs } from '$lib/stores/prefs.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import { parseBudget } from '$lib/utils/budget';
  import { highlightText } from '$lib/utils/highlight';
  import Settings from '$lib/components/Settings.svelte';
  import TagEdit from '$lib/components/TagEdit.svelte';

  const CONFIRM_TIMEOUT_MS = 3_000;
  const SEARCH_DEBOUNCE_MS = 200;

  let showNewForm = $state(false);
  let showSettings = $state(false);
  let showTagEdit = $state(false);
  let tagEditId = $state<number | null>(null);
  let newWorkingDir = $state('');
  let newModel = $state('claude-sonnet-4-6');
  let newTitle = $state('');
  let newBudget = $state('');
  let submitting = $state(false);
  let importInput: HTMLInputElement | undefined = $state();
  let importError = $state<string | null>(null);
  let importProgress = $state<{ done: number; total: number } | null>(null);
  let dragging = $state(false);

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
      importError = failures
        .map((f) => `${f.name}: ${f.error}`)
        .join('; ');
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

  let searchQuery = $state('');
  let searchResults = $state<api.SearchHit[]>([]);
  let searchError = $state<string | null>(null);
  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  let searchInput: HTMLInputElement | undefined = $state();

  $effect(() => {
    function onDocKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchInput?.focus();
        searchInput?.select();
      }
    }
    document.addEventListener('keydown', onDocKey);
    return () => document.removeEventListener('keydown', onDocKey);
  });

  function onSearchKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      searchQuery = '';
      searchResults = [];
      searchInput?.blur();
    }
  }

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

  /** Tag-driven defaults for the new-session form. When the sidebar
   * has one or more tags filter-selected, the highest-precedence tag
   * wins its working_dir / model defaults. Precedence matches
   * tag-memory precedence — canonical list order (pinned-first,
   * sort_order ASC, id ASC), last wins. Handles missing fields by
   * falling back to earlier tags in the precedence order. */
  function tagFilterDefaults(): { workingDir: string | null; model: string | null } {
    if (tags.selected.length === 0) return { workingDir: null, model: null };
    // `tags.list` is already in canonical order from the server.
    const selected = tags.list.filter((t) => tags.selected.includes(t.id));
    let workingDir: string | null = null;
    let model: string | null = null;
    for (const t of selected) {
      if (t.default_working_dir) workingDir = t.default_working_dir;
      if (t.default_model) model = t.default_model;
    }
    return { workingDir, model };
  }

  // Tag-chip state inside the new-session form. v0.2.13 requires ≥1
  // attached tag before the form can submit. Starts empty; the active
  // sidebar filter seeds it on open as a convenience.
  let newTagIds = $state<number[]>([]);
  let newTagDraft = $state('');
  let newTagError = $state<string | null>(null);

  const attachedNewTags = $derived(
    newTagIds
      .map((id) => tags.list.find((t) => t.id === id))
      .filter((t): t is api.Tag => t !== undefined)
  );

  const attachedNewSet = $derived(new Set(newTagIds));

  const newTagDraftLower = $derived(newTagDraft.trim().toLowerCase());

  const newTagSuggestions = $derived(
    newTagDraftLower === ''
      ? []
      : tags.list.filter(
          (t) =>
            !attachedNewSet.has(t.id) && t.name.toLowerCase().includes(newTagDraftLower)
        )
  );

  const newTagExactMatch = $derived(
    tags.list.find((t) => t.name.toLowerCase() === newTagDraftLower) ?? null
  );

  /** Precedence-aware defaults from the tags currently attached to the
   * new-session form. Mirrors tag-memory precedence (canonical list
   * order, last wins). Returns nulls for fields no attached tag sets. */
  function attachedTagDefaults(): { workingDir: string | null; model: string | null } {
    let workingDir: string | null = null;
    let model: string | null = null;
    // Iterate in canonical order — tags.list is already pinned/sort/id.
    for (const t of tags.list) {
      if (!attachedNewSet.has(t.id)) continue;
      if (t.default_working_dir) workingDir = t.default_working_dir;
      if (t.default_model) model = t.default_model;
    }
    return { workingDir, model };
  }

  function toggleNewForm() {
    if (showNewForm) {
      showNewForm = false;
      return;
    }
    // Seed attached tags from the active sidebar filter. User can add
    // or remove from this list before submitting.
    newTagIds = [...tags.selected];
    newTagDraft = '';
    newTagError = null;
    // Precedence: attached-tag defaults → user prefs → prior form value.
    const td = attachedTagDefaults();
    newWorkingDir = td.workingDir || prefs.defaultWorkingDir || newWorkingDir;
    newModel = td.model || prefs.defaultModel || newModel;
    showNewForm = true;
  }

  function attachNewTag(tag: api.Tag) {
    if (attachedNewSet.has(tag.id)) return;
    newTagIds = [...newTagIds, tag.id];
    newTagDraft = '';
    newTagError = null;
    // Apply this tag's defaults if the field is empty — don't clobber
    // a value the user already typed.
    if (!newWorkingDir.trim() && tag.default_working_dir) {
      newWorkingDir = tag.default_working_dir;
    }
    if (tag.default_model) newModel = tag.default_model;
  }

  function detachNewTag(id: number) {
    newTagIds = newTagIds.filter((x) => x !== id);
  }

  async function createAndAttachNewTag() {
    const name = newTagDraft.trim();
    if (name === '') return;
    newTagError = null;
    const created = await tags.create({ name });
    if (!created) {
      newTagError = tags.error;
      return;
    }
    attachNewTag(created);
  }

  function onNewTagKey(e: KeyboardEvent) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (newTagExactMatch) {
      if (!attachedNewSet.has(newTagExactMatch.id)) attachNewTag(newTagExactMatch);
      else newTagDraft = '';
      return;
    }
    createAndAttachNewTag();
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

  async function onCreate() {
    if (newTagIds.length === 0) {
      newTagError = 'Attach at least one tag before creating a session.';
      return;
    }
    submitting = true;
    const tagIds = [...newTagIds];
    const created = await sessions.create({
      working_dir: newWorkingDir.trim() || prefs.defaultWorkingDir || '/tmp',
      model: newModel.trim() || prefs.defaultModel || 'claude-sonnet-4-6',
      title: newTitle.trim() || null,
      max_budget_usd: parseBudget(newBudget),
      tag_ids: tagIds
    });
    submitting = false;
    if (created) {
      showNewForm = false;
      newWorkingDir = '';
      newTitle = '';
      newBudget = '';
      newTagIds = [];
      for (const id of tagIds) tags.bumpCount(id, +1);
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
<TagEdit bind:open={showTagEdit} tagId={tagEditId} />

{#snippet tagRow(tag: api.Tag, pinned: boolean)}
  {@const selected = tags.selected.includes(tag.id)}
  <li class="group flex items-stretch rounded hover:bg-slate-800 {selected ? 'bg-emerald-900/60' : ''}">
    <button
      type="button"
      class="flex-1 min-w-0 flex items-center justify-between gap-2 px-2 py-1 text-sm
        text-left transition {selected ? 'text-emerald-200' : 'text-slate-300'}"
      aria-pressed={selected}
      onclick={() => tags.toggleSelected(tag.id)}
    >
      <span class="flex items-center gap-1.5 min-w-0">
        {#if pinned}
          <span class="text-amber-400" aria-label="pinned">★</span>
        {/if}
        <span class="truncate">{tag.name}</span>
      </span>
      <span class="text-[10px] font-mono text-slate-500">
        {tag.session_count}
      </span>
    </button>
    <button
      type="button"
      class="px-1.5 text-xs text-slate-500 hover:text-slate-200
        opacity-0 group-hover:opacity-100"
      aria-label={`Edit tag ${tag.name}`}
      title="Edit tag (memory, defaults)"
      onclick={(e) => {
        e.stopPropagation();
        tagEditId = tag.id;
        showTagEdit = true;
      }}
    >
      ✎
    </button>
  </li>
{/snippet}

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
        onclick={toggleNewForm}
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

  <input
    type="search"
    placeholder="Search messages (⌘/Ctrl+K)"
    class="rounded bg-slate-950 border border-slate-800 px-2 py-1.5 text-sm
      focus:outline-none focus:border-slate-600"
    bind:value={searchQuery}
    bind:this={searchInput}
    onkeydown={onSearchKey}
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

      <section class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Tags <span class="text-rose-400">*</span></span>
        {#if attachedNewTags.length > 0}
          <ul class="flex flex-wrap gap-1" aria-label="Attached tags">
            {#each attachedNewTags as tag (tag.id)}
              <li class="flex items-center gap-1 rounded bg-slate-900 px-2 py-0.5">
                {#if tag.pinned}
                  <span class="text-amber-400" aria-label="pinned">★</span>
                {/if}
                <span>{tag.name}</span>
                <button
                  type="button"
                  class="text-slate-500 hover:text-rose-400"
                  aria-label={`Detach ${tag.name}`}
                  onclick={() => detachNewTag(tag.id)}
                >
                  ✕
                </button>
              </li>
            {/each}
          </ul>
        {/if}
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm"
          placeholder="Add a tag (Enter to attach or create)"
          aria-label="New-session tag name"
          bind:value={newTagDraft}
          onkeydown={onNewTagKey}
        />
        {#if newTagSuggestions.length > 0}
          <ul class="flex flex-wrap gap-1" aria-label="Tag suggestions">
            {#each newTagSuggestions as tag (tag.id)}
              <li>
                <button
                  type="button"
                  class="rounded bg-slate-900 hover:bg-slate-700 px-2 py-0.5"
                  onclick={() => attachNewTag(tag)}
                >
                  + {tag.name}
                </button>
              </li>
            {/each}
          </ul>
        {:else if newTagDraft.trim() !== '' && !newTagExactMatch}
          <button
            type="button"
            class="self-start rounded bg-emerald-700 hover:bg-emerald-600 px-2 py-0.5"
            onclick={createAndAttachNewTag}
          >
            + Create "{newTagDraft.trim()}"
          </button>
        {/if}
        {#if newTagError}
          <p class="text-rose-400">{newTagError}</p>
        {/if}
      </section>

      <button
        type="submit"
        class="rounded bg-emerald-600 hover:bg-emerald-500 px-2 py-1 text-sm mt-1 disabled:opacity-50"
        disabled={submitting || newTagIds.length === 0}
        title={newTagIds.length === 0 ? 'Attach at least one tag' : ''}
      >
        {submitting ? 'Creating…' : 'Create session'}
      </button>
    </form>
  {/if}

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

  {#if !searchQuery.trim() && tags.list.length > 0}
    {@const pinned = tags.list.filter((t) => t.pinned)}
    {@const unpinned = tags.list.filter((t) => !t.pinned)}
    <section class="flex flex-col gap-1">
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-sm uppercase tracking-wider text-slate-400">Tags</h2>
        <button
          type="button"
          class="text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5
            bg-slate-800 hover:bg-slate-700 text-slate-300"
          aria-label="Toggle tag combine mode"
          title={tags.mode === 'any'
            ? 'Any: match sessions with any selected tag'
            : 'All: match sessions with every selected tag'}
          onclick={() => (tags.mode = tags.mode === 'any' ? 'all' : 'any')}
        >
          {tags.mode === 'any' ? 'Any' : 'All'}
        </button>
      </div>
      <ul class="flex flex-col gap-0.5">
        {#each pinned as tag (tag.id)}
          {@render tagRow(tag, true)}
        {/each}
        {#if pinned.length > 0 && unpinned.length > 0}
          <li class="h-px bg-slate-800 my-1" aria-hidden="true"></li>
        {/if}
        {#each unpinned as tag (tag.id)}
          {@render tagRow(tag, false)}
        {/each}
      </ul>
    </section>
  {/if}

  {#if tags.hasFilter && !searchQuery.trim()}
    <button
      type="button"
      class="self-start flex items-center gap-1 rounded bg-slate-800 hover:bg-slate-700
        px-2 py-1 text-[11px] text-slate-300"
      onclick={() => tags.clearSelection()}
    >
      <span>Filter: {tags.selected.length} tag{tags.selected.length === 1 ? '' : 's'}</span>
      <span class="text-slate-500">✕</span>
    </button>
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

<style>
  .snippet :global(mark) {
    background-color: rgb(234 179 8 / 0.35);
    color: rgb(253 224 71);
    border-radius: 0.125rem;
    padding: 0 0.125rem;
  }
</style>
