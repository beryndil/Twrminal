<script lang="ts">
  /**
   * Memories page — Phase 4 of the v1.0.0 dashboard redesign.
   *
   * The mockup put a top-level `/memories` route in the sidebar nav
   * for browsing the durable per-tag context that gets stitched into
   * every session's system prompt. Each Bearings tag can carry one
   * `tag_memory` row (markdown content); when a session has that tag
   * attached, the memory is injected as a `tag_memory` system-prompt
   * layer. Pre-Phase-4 the only edit affordance was the pencil icon
   * next to a tag in the sidebar filter panel — this page surfaces
   * the whole memory inventory in one place.
   *
   * Backed by `GET /api/tags/memories` — a Phase-4 aggregate endpoint
   * that joins `tag_memories` with the parent tag's display fields
   * (name, color, group) and returns the list in one round-trip,
   * sorted by most-recent edit first server-side. Editing reuses the
   * existing `TagEdit.svelte` modal (the same one the sidebar pencil
   * opens) so the editor invariants — markdown preview, save/delete,
   * runner respawn on save — stay in one place.
   *
   * The memory body is collapsed to a 4-line preview to keep the row
   * heights honest; clicking Edit opens the full editor. Empty state
   * names where to create the first memory rather than offering an
   * inline `+ Memory` button: memories are tag-scoped, so creation
   * naturally belongs to the tag UI, not a parallel surface here.
   */
  import { onMount } from 'svelte';
  import * as api from '$lib/api';
  import { formatAbsolute } from '$lib/utils/datetime';
  import TagEdit from '$lib/components/TagEdit.svelte';

  let memories = $state<api.TagMemoryWithTag[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let editOpen = $state(false);
  let editingTagId = $state<number | null>(null);

  async function refresh(): Promise<void> {
    loading = true;
    error = null;
    try {
      memories = await api.listTagMemories();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  // Re-fetch when the editor closes — saves and deletes happen inside
  // the modal and there's no shared store to invalidate, so a poll on
  // close is the simplest path back to a consistent view.
  let prevEditOpen = false;
  $effect(() => {
    const open = editOpen;
    if (prevEditOpen && !open) void refresh();
    prevEditOpen = open;
  });

  onMount(() => {
    void refresh();
  });

  function openEditor(tagId: number): void {
    editingTagId = tagId;
    editOpen = true;
  }
</script>

<TagEdit bind:open={editOpen} tagId={editingTagId} />

<section class="flex h-full flex-col overflow-hidden" data-testid="memories-page">
  <header
    class="flex shrink-0 items-baseline justify-between gap-3 border-b border-slate-800
      px-6 py-4"
  >
    <div>
      <h1 class="text-lg font-medium text-slate-200">Memories</h1>
      <p class="text-xs text-slate-500">
        Per-tag durable context, injected into every session's system prompt.
      </p>
    </div>
    {#if memories.length > 0}
      <span class="font-mono text-xs text-slate-500">
        {memories.length} memor{memories.length === 1 ? 'y' : 'ies'}
      </span>
    {/if}
  </header>

  <div class="flex-1 overflow-y-auto px-6 py-4">
    {#if loading}
      <p class="text-sm text-slate-500" data-testid="memories-loading">Loading…</p>
    {:else if error}
      <div
        class="rounded-md border border-rose-900/40 bg-rose-950/30 p-3 text-sm text-rose-300"
        data-testid="memories-error"
      >
        Failed to load memories: {error}
        <button
          type="button"
          class="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-200 hover:bg-slate-700"
          onclick={refresh}
        >
          Retry
        </button>
      </div>
    {:else if memories.length === 0}
      <div
        class="rounded-md border border-slate-800 bg-slate-900 px-5 py-6 text-center"
        data-testid="memories-empty"
      >
        <p class="mb-1 text-sm font-medium text-slate-200">No memories yet</p>
        <p class="mx-auto max-w-md text-xs text-slate-500">
          Add a memory by clicking the
          <span class="text-slate-300">✎</span> pencil next to any tag in the sidebar's
          <span class="text-slate-300">tag-filter list</span> (under Recent Sessions). Memories are durable
          per-tag context stitched into the system prompt of every session that carries the tag.
        </p>
      </div>
    {:else}
      <ul class="flex flex-col gap-3" data-testid="memories-list">
        {#each memories as mem (mem.tag_id)}
          <li
            class="rounded-md border border-slate-800 bg-slate-900 p-4"
            data-testid="memory-row-{mem.tag_id}"
          >
            <header class="mb-2 flex items-baseline justify-between gap-3">
              <div class="flex min-w-0 items-center gap-2">
                <span
                  class="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                  style:background-color={mem.tag_color ?? 'rgb(var(--bearings-slate-600))'}
                  aria-hidden="true"
                ></span>
                <span class="truncate font-mono text-sm font-medium text-slate-200">
                  {mem.tag_name}
                </span>
                {#if mem.tag_group === 'severity'}
                  <span
                    class="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wider
                      text-slate-400"
                  >
                    severity
                  </span>
                {/if}
              </div>
              <div class="flex shrink-0 items-center gap-3">
                <time class="font-mono text-[11px] text-slate-500" datetime={mem.updated_at}>
                  {formatAbsolute(mem.updated_at)}
                </time>
                <button
                  type="button"
                  class="rounded bg-slate-800 px-2 py-1 text-[11px] text-slate-300
                    hover:bg-slate-700"
                  onclick={() => openEditor(mem.tag_id)}
                  data-testid="memory-edit-{mem.tag_id}"
                  aria-label="Edit memory for {mem.tag_name}"
                >
                  Edit
                </button>
              </div>
            </header>
            <pre
              class="line-clamp-4 max-h-[5.5rem] overflow-hidden whitespace-pre-wrap break-words
                font-mono text-xs text-slate-400">{mem.content}</pre>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>
