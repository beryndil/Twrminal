<script lang="ts">
  import { tags } from '$lib/stores/tags.svelte';
  import TagEdit from '$lib/components/TagEdit.svelte';
  import type { Tag } from '$lib/api';

  let showTagEdit = $state(false);
  let tagEditId = $state<number | null>(null);

  function openEdit(id: number, e: MouseEvent) {
    e.stopPropagation();
    tagEditId = id;
    showTagEdit = true;
  }
</script>

<TagEdit bind:open={showTagEdit} tagId={tagEditId} />

{#snippet tagRow(tag: Tag, pinned: boolean)}
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
      onclick={(e) => openEdit(tag.id, e)}
    >
      ✎
    </button>
  </li>
{/snippet}

{#if tags.list.length > 0}
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

{#if tags.hasFilter}
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
