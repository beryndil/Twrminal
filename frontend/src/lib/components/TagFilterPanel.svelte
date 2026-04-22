<script lang="ts">
  import { tags } from '$lib/stores/tags.svelte';
  import TagEdit from '$lib/components/TagEdit.svelte';
  import SeverityShield from '$lib/components/icons/SeverityShield.svelte';
  import TagIcon from '$lib/components/icons/TagIcon.svelte';
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

{#snippet generalTagRow(tag: Tag, pinned: boolean)}
  {@const selected = tags.selected.includes(tag.id)}
  <li class="group flex items-stretch rounded hover:bg-slate-800 {selected ? 'bg-emerald-900/60' : ''}">
    <button
      type="button"
      class="flex-1 min-w-0 flex items-center justify-between gap-1.5 px-2 py-0.5 text-xs
        text-left transition {selected ? 'text-emerald-200' : 'text-slate-300'}"
      aria-pressed={selected}
      title="Click to filter by this tag · Shift+click to add to the selection"
      onclick={(e) => tags.selectGeneral(tag.id, { additive: e.shiftKey })}
    >
      <span class="flex items-center gap-1 min-w-0">
        <TagIcon color={tag.color} title={tag.name} size={11} />
        {#if pinned}
          <span class="text-amber-400" aria-label="pinned">★</span>
        {/if}
        <span class="truncate">{tag.name}</span>
      </span>
      <span class="text-[10px] font-mono tabular-nums inline-flex items-baseline gap-1">
        <span class={tag.open_session_count > 0 ? 'text-emerald-400' : 'text-slate-500'}>
          {tag.open_session_count}
        </span>
        <span class="text-slate-500">{tag.session_count}</span>
      </span>
    </button>
    <button
      type="button"
      class="px-1 text-[11px] text-slate-500 hover:text-slate-200
        opacity-0 group-hover:opacity-100"
      aria-label={`Edit tag ${tag.name}`}
      title="Edit tag (memory, defaults)"
      onclick={(e) => openEdit(tag.id, e)}
    >
      ✎
    </button>
  </li>
{/snippet}

{#snippet severityTagRow(tag: Tag)}
  {@const selected = tags.selectedSeverity.includes(tag.id)}
  <li class="group flex items-stretch rounded hover:bg-slate-800 {selected ? 'bg-emerald-900/60' : ''}">
    <button
      type="button"
      class="flex-1 min-w-0 flex items-center justify-between gap-1.5 px-2 py-0.5 text-xs
        text-left transition {selected ? 'text-emerald-200' : 'text-slate-300'}"
      aria-pressed={selected}
      title="Click to filter by this severity · Shift+click to add to the selection"
      onclick={(e) => tags.selectSeverity(tag.id, { additive: e.shiftKey })}
    >
      <span class="flex items-center gap-1 min-w-0">
        <SeverityShield color={tag.color} title={tag.name} size={11} />
        <span class="truncate">{tag.name}</span>
      </span>
      <span class="text-[10px] font-mono tabular-nums inline-flex items-baseline gap-1">
        <span class={tag.open_session_count > 0 ? 'text-emerald-400' : 'text-slate-500'}>
          {tag.open_session_count}
        </span>
        <span class="text-slate-500">{tag.session_count}</span>
      </span>
    </button>
    <button
      type="button"
      class="px-1 text-[11px] text-slate-500 hover:text-slate-200
        opacity-0 group-hover:opacity-100"
      aria-label={`Edit severity tag ${tag.name}`}
      title="Edit severity (color, name)"
      onclick={(e) => openEdit(tag.id, e)}
    >
      ✎
    </button>
  </li>
{/snippet}

{#if tags.list.length > 0}
  {@const pinned = tags.generalList.filter((t) => t.pinned)}
  {@const unpinned = tags.generalList.filter((t) => !t.pinned)}
  <section class="flex flex-col gap-1">
    <!-- Collapsible header for the whole panel. Mirrors the closed-
         sessions group pattern further down the sidebar so there's
         one collapse idiom throughout. Persists to localStorage via
         the store (v0.2.14). -->
    <button
      type="button"
      class="w-full flex items-center justify-between px-1 py-0.5 text-xs
        uppercase tracking-wider text-slate-400 hover:text-slate-200"
      aria-expanded={!tags.panelCollapsed}
      aria-controls="tag-filter-panel-body"
      onclick={() => tags.togglePanel()}
      data-testid="tag-panel-toggle"
    >
      <span>Tags</span>
      <span class="flex items-center gap-1">
        {#if tags.panelCollapsed && (tags.hasFilter || tags.hasSeverityFilter)}
          <!-- When collapsed with an active filter, show a tiny chip
               count so Daisy can tell filters are on without needing
               to expand the panel. -->
          <span class="text-[10px] normal-case tracking-normal text-emerald-300">
            {tags.selected.length + tags.selectedSeverity.length} on
          </span>
        {/if}
        <span aria-hidden="true">{tags.panelCollapsed ? '▸' : '▾'}</span>
      </span>
    </button>

    {#if !tags.panelCollapsed}
      <div id="tag-filter-panel-body" class="flex flex-col gap-1">
        <!-- General (user-editable) tag group. Multi-select is
             shift-click (Finder semantics); combination is always AND
             so a session must carry every selected tag to appear. No
             Any/All toggle — one click rule in and out of the panel. -->
        <ul class="flex flex-col gap-0.5">
          {#each pinned as tag (tag.id)}
            {@render generalTagRow(tag, true)}
          {/each}
          {#if pinned.length > 0 && unpinned.length > 0}
            <li class="h-px bg-slate-800 my-1" aria-hidden="true"></li>
          {/if}
          {#each unpinned as tag (tag.id)}
            {@render generalTagRow(tag, false)}
          {/each}
        </ul>

        {#if tags.severityList.length > 0}
          <!-- HR divider between the two tag groups. -->
          <hr class="border-0 border-t border-slate-800 my-1" aria-hidden="true" />
          <h3 class="px-1 text-[10px] uppercase tracking-wider text-slate-500">
            Severity
          </h3>
          <ul class="flex flex-col gap-0.5" data-testid="severity-list">
            {#each tags.severityList as tag (tag.id)}
              {@render severityTagRow(tag)}
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </section>
{/if}

{#if tags.hasFilter || tags.hasSeverityFilter}
  <div class="flex flex-wrap gap-1">
    {#if tags.hasFilter}
      <button
        type="button"
        class="flex items-center gap-1 rounded bg-slate-800 hover:bg-slate-700
          px-1.5 py-0.5 text-[11px] text-slate-300"
        onclick={() => tags.clearSelection()}
      >
        <span>{tags.selected.length} tag{tags.selected.length === 1 ? '' : 's'}</span>
        <span class="text-slate-500">✕</span>
      </button>
    {/if}
    {#if tags.hasSeverityFilter}
      <button
        type="button"
        class="flex items-center gap-1 rounded bg-slate-800 hover:bg-slate-700
          px-1.5 py-0.5 text-[11px] text-slate-300"
        onclick={() => tags.clearSeveritySelection()}
      >
        <span>
          {tags.selectedSeverity.length} severit{tags.selectedSeverity.length === 1 ? 'y' : 'ies'}
        </span>
        <span class="text-slate-500">✕</span>
      </button>
    {/if}
  </div>
{/if}
