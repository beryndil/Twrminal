<script lang="ts">
  import { tags, SEVERITY_NONE_ID } from '$lib/stores/tags.svelte';
  import { contextmenu } from '$lib/actions/contextmenu';
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
  <li
    class="group flex items-stretch rounded hover:bg-slate-800 {selected ? 'bg-emerald-900/60' : ''}"
    use:contextmenu={{ target: { type: 'tag', id: tag.id } }}
  >
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

{#snippet severityNoneRow()}
  {@const noneSelected = tags.selectedSeverity.includes(SEVERITY_NONE_ID)}
  <!-- Virtual "No severity" row. Finds sessions orphaned by a
       deleted severity tag (or ones that pre-date the migration
       and somehow dodged the backfill). The sentinel `-1` flows
       through selectedSeverity and arrives at the backend as
       `severity_tags=-1`; the store there maps it to a NOT EXISTS
       clause so these rows are findable without inventing a real
       tag. Snipped out rather than inlined so the `{@const}` sits
       in a legal parent per Svelte's `const_tag_invalid_placement`
       rule. -->
  <li
    class="group flex items-stretch rounded hover:bg-slate-800 {noneSelected
      ? 'bg-emerald-900/60'
      : ''}"
    data-testid="severity-none-row"
  >
    <button
      type="button"
      class="flex-1 min-w-0 flex items-center justify-between gap-1.5 px-2 py-0.5 text-xs
        text-left transition {noneSelected ? 'text-emerald-200' : 'text-slate-400'}"
      aria-pressed={noneSelected}
      title="Sessions with no severity tag attached · Shift+click to add to the selection"
      onclick={(e) => tags.selectSeverity(SEVERITY_NONE_ID, { additive: e.shiftKey })}
    >
      <span class="flex items-center gap-1 min-w-0">
        <!-- color=null renders the dim slate fallback shield, which
             visually matches the "no severity" state as it appears
             next to session titles in the sidebar. -->
        <SeverityShield color={null} title="No severity" size={11} />
        <span class="truncate italic">No severity</span>
      </span>
    </button>
  </li>
{/snippet}

{#snippet severityTagRow(tag: Tag)}
  {@const selected = tags.selectedSeverity.includes(tag.id)}
  <li
    class="group flex items-stretch rounded hover:bg-slate-800 {selected ? 'bg-emerald-900/60' : ''}"
    use:contextmenu={{ target: { type: 'tag', id: tag.id } }}
  >
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
    <!-- v0.7.4 header row. The old collapse button moved to the
         bottom of the panel (paired with an HR divider there); the
         header now carries the panel label plus two action buttons —
         `All` selects every general tag, `None` clears the
         selection. Under the v0.7.4 OR semantics, All ≡ "show every
         session" and None ≡ "show nothing", so these are also the
         fast way to flip the sidebar between full-view and empty. -->
    <div
      class="w-full flex items-center justify-between px-1 py-0.5 text-xs
        uppercase tracking-wider text-slate-400"
    >
      <span>Tags</span>
      <div class="flex items-center gap-1 normal-case tracking-normal">
        <button
          type="button"
          class="px-1.5 py-0.5 rounded text-[11px] text-slate-300
            hover:text-slate-100 hover:bg-slate-800"
          onclick={() => tags.selectAllGeneral()}
          data-testid="tag-panel-all"
          title="Select every general tag (show every session)"
        >
          All
        </button>
        <button
          type="button"
          class="px-1.5 py-0.5 rounded text-[11px] text-slate-300
            hover:text-slate-100 hover:bg-slate-800"
          onclick={() => tags.clearSelection()}
          data-testid="tag-panel-none"
          title="Clear the general-tag selection (show nothing)"
        >
          None
        </button>
      </div>
    </div>

    {#if !tags.panelCollapsed}
      <div id="tag-filter-panel-body" class="flex flex-col gap-1">
        <!-- General (user-editable) tag group. Multi-select is
             shift-click (Finder semantics); combination is OR
             (v0.7.4) so a session matches if it carries any
             selected tag. Empty selection shows nothing; use the
             All / None buttons in the header to flip in and out of
             that state quickly. -->
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
            {@render severityNoneRow()}
          </ul>
        {/if}
      </div>
    {/if}

    <!-- v0.7.4: collapse toggle moved here (bottom of the panel) so
         the header can host the All/None shortcuts. Chevron is `▴`
         when expanded (points up into the body it collapses) and
         `▾` when collapsed (points down toward what would be
         revealed). Persists to localStorage via the store. -->
    <hr class="border-0 border-t border-slate-800 my-1" aria-hidden="true" />
    <button
      type="button"
      class="w-full flex items-center justify-between px-1 py-0.5 text-[10px]
        uppercase tracking-wider text-slate-500 hover:text-slate-200"
      aria-expanded={!tags.panelCollapsed}
      aria-controls="tag-filter-panel-body"
      onclick={() => tags.togglePanel()}
      data-testid="tag-panel-toggle"
    >
      <span>{tags.panelCollapsed ? 'Show tags' : 'Hide tags'}</span>
      <span class="flex items-center gap-1">
        {#if tags.panelCollapsed && (tags.hasFilter || tags.hasSeverityFilter)}
          <!-- Active-filter breadcrumb stays reachable through the
               collapsed footer so Daisy can tell filters are on
               without expanding the panel. -->
          <span class="text-[10px] normal-case tracking-normal text-emerald-300">
            {tags.selected.length + tags.selectedSeverity.length} on
          </span>
        {/if}
        <span aria-hidden="true">{tags.panelCollapsed ? '▾' : '▴'}</span>
      </span>
    </button>
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
