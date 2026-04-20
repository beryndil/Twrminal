<script lang="ts">
  import { listDir, type FsEntry } from '$lib/api/fs';

  let {
    value = $bindable(''),
    placeholder = 'click to choose…'
  }: { value?: string; placeholder?: string } = $props();

  let open = $state(false);
  let currentPath = $state('');
  let parent = $state<string | null>(null);
  let entries = $state<FsEntry[]>([]);
  let showHidden = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function fetchList(path: string | null): Promise<void> {
    loading = true;
    error = null;
    try {
      const result = await listDir({ path, hidden: showHidden });
      currentPath = result.path;
      parent = result.parent;
      entries = result.entries;
    } catch (e) {
      // Leave currentPath / entries untouched so the user still sees
      // the last good directory while the error is on screen.
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function openDialog() {
    open = true;
    // Seed from the current value, or $HOME (server-side) when empty.
    await fetchList(value.trim() || null);
  }

  function closeDialog() {
    open = false;
  }

  async function descend(entry: FsEntry) {
    await fetchList(entry.path);
  }

  async function ascend() {
    if (parent !== null) await fetchList(parent);
  }

  async function toggleHidden() {
    showHidden = !showHidden;
    await fetchList(currentPath);
  }

  function useThis() {
    value = currentPath;
    open = false;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') closeDialog();
  }

  const crumbs = $derived.by(() => {
    if (!currentPath) return [] as Array<{ label: string; path: string }>;
    const segments = currentPath.split('/').filter((s) => s.length > 0);
    const out = [{ label: '/', path: '/' }];
    let acc = '';
    for (const seg of segments) {
      acc += '/' + seg;
      out.push({ label: seg, path: acc });
    }
    return out;
  });
</script>

<button
  type="button"
  class="w-full text-left rounded bg-slate-950 border border-slate-800 hover:border-slate-600
    px-2 py-2 text-sm font-mono truncate"
  class:text-slate-200={value}
  class:text-slate-500={!value}
  onclick={openDialog}
  aria-label="Folder path"
  title={value || placeholder}
>
  {value || placeholder}
</button>

{#if open}
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4"
    role="dialog"
    aria-modal="true"
    aria-label="Choose folder"
    onkeydown={onKeydown}
    tabindex="-1"
  >
    <div
      class="w-full max-w-lg rounded-lg border border-slate-800 bg-slate-900 p-4 shadow-2xl
        flex flex-col gap-3"
    >
      <header class="flex items-start justify-between">
        <h2 class="text-sm font-medium text-slate-200">Choose folder</h2>
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Close folder picker"
          onclick={closeDialog}
        >
          ✕
        </button>
      </header>

      <nav
        class="flex flex-wrap items-center gap-0.5 text-xs text-slate-400"
        aria-label="Path breadcrumb"
      >
        {#each crumbs as crumb, i (crumb.path)}
          {#if i > 0}<span class="text-slate-700">/</span>{/if}
          <button
            type="button"
            class="rounded px-1 hover:bg-slate-800 hover:text-slate-200 font-mono"
            onclick={() => fetchList(crumb.path)}
          >
            {crumb.label}
          </button>
        {/each}
      </nav>

      <div class="flex items-center justify-between gap-2 text-xs">
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-2 py-1 text-slate-200 disabled:opacity-40"
          onclick={ascend}
          disabled={parent === null}
          aria-label="Go to parent directory"
        >
          ⬆ parent
        </button>
        <label class="inline-flex items-center gap-1 text-slate-400">
          <input
            type="checkbox"
            class="accent-emerald-500"
            checked={showHidden}
            onchange={toggleHidden}
          />
          <span>hidden</span>
        </label>
      </div>

      {#if loading}
        <p class="text-xs text-slate-500">loading…</p>
      {:else if error}
        <p class="text-xs text-rose-400">{error}</p>
      {:else if entries.length === 0}
        <p class="text-xs text-slate-600">(no subdirectories)</p>
      {:else}
        <ul
          class="grid grid-cols-2 gap-1 max-h-64 overflow-y-auto"
          aria-label="Subdirectories"
        >
          {#each entries as entry (entry.path)}
            <li>
              <button
                type="button"
                class="w-full text-left truncate rounded bg-slate-900 hover:bg-slate-800 px-2 py-1 text-xs font-mono text-slate-200"
                onclick={() => descend(entry)}
                title={entry.path}
              >
                {entry.name}
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      <footer class="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-3 py-1 text-xs text-slate-200"
          onclick={closeDialog}
        >
          Cancel
        </button>
        <button
          type="button"
          class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-1 text-xs text-white"
          onclick={useThis}
        >
          Use this folder
        </button>
      </footer>
    </div>
  </div>
{/if}
