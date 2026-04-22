<script lang="ts">
  import { listDir, type FsEntry } from '$lib/api/fs';

  /**
   * In-app file picker. Opens as a centered Bearings-styled modal (same
   * visual language as FolderPicker / SessionPickerModal / ApprovalModal)
   * so we don't spawn an OS window for what should feel like part of
   * the chat pane.
   *
   * Multi-select: selection persists as the user walks across
   * directories, so they can grab files from several folders in a
   * single open. Clicking a dir descends; clicking a file toggles its
   * selection. Enter confirms; Escape cancels.
   */

  let {
    open = false,
    start = null,
    onPick,
    onCancel
  }: {
    open?: boolean;
    /** Directory to root the picker at on open. Falls back to $HOME
     * server-side when null/empty. */
    start?: string | null;
    onPick: (paths: string[]) => void;
    onCancel: () => void;
  } = $props();

  let currentPath = $state('');
  let parent = $state<string | null>(null);
  let entries = $state<FsEntry[]>([]);
  let showHidden = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);
  // Absolute paths keyed for O(1) toggle. Persists across dir navigation
  // so multi-select can span folders.
  let selected = $state<Set<string>>(new Set());

  async function fetchList(path: string | null): Promise<void> {
    loading = true;
    error = null;
    try {
      const result = await listDir({ path, hidden: showHidden, includeFiles: true });
      currentPath = result.path;
      parent = result.parent;
      entries = result.entries;
    } catch (e) {
      // Leave the previous listing on screen so the user still has
      // context while they read the error.
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  // When `open` flips true, seed the listing from `start`. `open` is a
  // prop (not internal state) so the caller keeps control — prevents a
  // stale listing flashing in on the next open.
  $effect(() => {
    if (open) {
      selected = new Set();
      error = null;
      void fetchList(start && start.trim() ? start : null);
    }
  });

  async function toggleHidden() {
    showHidden = !showHidden;
    await fetchList(currentPath);
  }

  async function onEntryClick(entry: FsEntry) {
    if (entry.is_dir) {
      await fetchList(entry.path);
      return;
    }
    const next = new Set(selected);
    if (next.has(entry.path)) next.delete(entry.path);
    else next.add(entry.path);
    selected = next;
  }

  async function ascend() {
    if (parent !== null) await fetchList(parent);
  }

  function confirm() {
    if (selected.size === 0) return;
    onPick([...selected]);
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
      return;
    }
    if (e.key === 'Enter' && selected.size > 0) {
      e.preventDefault();
      confirm();
    }
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

  const confirmLabel = $derived(
    selected.size === 0
      ? 'Select a file'
      : selected.size === 1
        ? 'Use this file'
        : `Use ${selected.size} files`
  );
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4"
    role="dialog"
    aria-modal="true"
    aria-label="Choose files"
    onkeydown={onKeydown}
    onclick={(e) => {
      // Click on the backdrop (not the card) cancels, matching the
      // behavior SessionPickerModal already trains users on.
      if (e.target === e.currentTarget) onCancel();
    }}
    tabindex="-1"
  >
    <div
      class="w-full max-w-lg rounded-lg border border-slate-800 bg-slate-900 p-4 shadow-2xl
        flex flex-col gap-3"
    >
      <header class="flex items-start justify-between">
        <h2 class="text-sm font-medium text-slate-200">Attach files</h2>
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Close file picker"
          onclick={onCancel}
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
        <p class="text-xs text-slate-600">(empty directory)</p>
      {:else}
        <ul
          class="flex flex-col gap-0.5 max-h-72 overflow-y-auto"
          aria-label="Directory contents"
        >
          {#each entries as entry (entry.path)}
            <li>
              <button
                type="button"
                class="w-full text-left flex items-center gap-2 truncate rounded px-2 py-1 text-xs font-mono
                  {entry.is_dir
                    ? 'bg-slate-900 hover:bg-slate-800 text-slate-200'
                    : selected.has(entry.path)
                      ? 'bg-sky-900/40 border border-sky-600/50 text-sky-100'
                      : 'bg-slate-900 hover:bg-slate-800 text-slate-300 border border-transparent'}"
                onclick={() => onEntryClick(entry)}
                title={entry.path}
                data-testid={entry.is_dir ? 'fp-dir' : 'fp-file'}
              >
                <span class="text-slate-500" aria-hidden="true">
                  {entry.is_dir ? '▸' : selected.has(entry.path) ? '☑' : '☐'}
                </span>
                <span class="truncate">{entry.name}</span>
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      {#if selected.size > 0}
        <p class="text-[10px] text-slate-500">
          {selected.size} selected · click again to deselect · selection persists across folders
        </p>
      {/if}

      <footer class="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-3 py-1 text-xs text-slate-200"
          onclick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-1 text-xs text-white
            disabled:opacity-40 disabled:cursor-not-allowed"
          onclick={confirm}
          disabled={selected.size === 0}
          data-testid="fp-confirm"
        >
          {confirmLabel}
        </button>
      </footer>
    </div>
  </div>
{/if}
