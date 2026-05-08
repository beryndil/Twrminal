<script lang="ts">
  /**
   * MemoriesIndex — global flat-list view of every memory across all
   * tags (gap-cycle-13-007; ``docs/behavior/memories.md``).
   *
   * Renders:
   *
   * 1. A chip row for filtering by tag — chips are derived from the
   *    tag names in the response; clicking a chip narrows the list to
   *    that tag. Clicking an active chip clears the filter.
   * 2. A flat list of memory rows sorted by tag name then memory title
   *    (ordering is provided by the backend ``GET /api/memories``).
   * 3. An empty state only when the response is [] (no memories across
   *    any tag). "Pick a tag" copy is NOT shown here — the index is
   *    the default view regardless of tag selection state.
   *
   * ``onRowClick`` is the seam that the parent page uses to switch
   * into the per-tag editor view for a selected memory.
   */
  import { onMount } from "svelte";

  import { listAllMemories, type AllMemoriesRow } from "../../api/memories";
  import { MEMORIES_STRINGS } from "../../config";

  interface Props {
    /** Called when the user clicks a memory row. */
    onRowClick?: (row: AllMemoriesRow) => void;
    // Test-injectable seam for the API call.
    listAllMemoriesFn?: typeof listAllMemories;
  }

  const { onRowClick = () => {}, listAllMemoriesFn = listAllMemories }: Props = $props();

  let rows = $state<AllMemoriesRow[]>([]);
  let loading = $state(true);
  let error = $state<Error | null>(null);
  /** Tag id chip filter; ``null`` = show all. */
  let filterTagId = $state<number | null>(null);

  // Unique tags derived from the flat list, in the order they first appear.
  const uniqueTags = $derived(
    (() => {
      const seen = new Set<number>();
      const out: { id: number; name: string; color: string | null }[] = [];
      for (const row of rows) {
        if (!seen.has(row.tag_id)) {
          seen.add(row.tag_id);
          out.push({ id: row.tag_id, name: row.tag_name, color: row.tag_color });
        }
      }
      return out;
    })(),
  );

  const filteredRows = $derived(
    filterTagId === null ? rows : rows.filter((r) => r.tag_id === filterTagId),
  );

  function toggleFilter(tagId: number): void {
    filterTagId = filterTagId === tagId ? null : tagId;
  }

  onMount(() => {
    void (async () => {
      try {
        rows = await listAllMemoriesFn();
      } catch (e) {
        error = e instanceof Error ? e : new Error(String(e));
      } finally {
        loading = false;
      }
    })();
  });
</script>

<section
  class="memories-index flex h-full flex-col"
  data-testid="memories-index"
  aria-label={MEMORIES_STRINGS.indexAriaLabel}
>
  <header class="memories-index__header border-b border-border p-3">
    <h2 class="text-sm font-semibold text-fg-strong">{MEMORIES_STRINGS.paneHeading}</h2>

    {#if uniqueTags.length > 1}
      <div
        class="memories-index__chips mt-2 flex flex-wrap gap-1"
        data-testid="memories-index-chips"
        role="group"
        aria-label={MEMORIES_STRINGS.indexChipGroupLabel}
      >
        {#each uniqueTags as tag (tag.id)}
          <button
            type="button"
            class="rounded-full border px-2 py-0.5 text-xs transition-colors {filterTagId === tag.id
              ? 'border-accent bg-accent/20 text-fg-strong'
              : 'border-border bg-surface-2 text-fg-muted hover:bg-surface-0'}"
            data-testid="memories-index-chip"
            data-tag-id={tag.id}
            aria-pressed={filterTagId === tag.id}
            onclick={() => toggleFilter(tag.id)}
          >
            {tag.name}
          </button>
        {/each}
      </div>
    {/if}
  </header>

  <div class="memories-index__body flex-1 overflow-y-auto p-2">
    {#if loading}
      <p class="text-sm text-fg-muted" data-testid="memories-index-loading">
        {MEMORIES_STRINGS.loading}
      </p>
    {:else if error !== null}
      <p class="text-sm text-red-400" data-testid="memories-index-error">
        {MEMORIES_STRINGS.indexLoadFailed}
      </p>
    {:else if rows.length === 0}
      <p class="text-sm text-fg-muted" data-testid="memories-index-empty">
        {MEMORIES_STRINGS.indexEmpty}
      </p>
    {:else}
      <ul class="flex flex-col gap-1" data-testid="memories-index-list">
        {#each filteredRows as row (row.memory_id)}
          <li
            class="memories-index__row rounded border border-border bg-surface-1 p-2 {row.enabled
              ? ''
              : 'opacity-60'}"
            data-testid="memories-index-row"
            data-memory-id={row.memory_id}
            data-tag-id={row.tag_id}
            data-enabled={row.enabled ? "true" : "false"}
          >
            <button type="button" class="w-full text-left" onclick={() => onRowClick(row)}>
              <div class="flex items-baseline gap-2">
                <span
                  class="memories-index__row-title truncate text-sm font-medium text-fg-strong"
                  data-testid="memories-index-row-title"
                >
                  {row.memory_title}
                </span>
                <span
                  class="memories-index__row-tag shrink-0 rounded-sm bg-surface-2 px-1 py-0.5 text-[10px] text-fg-muted"
                  data-testid="memories-index-row-tag"
                >
                  {row.tag_name}
                </span>
                {#if !row.enabled}
                  <span class="shrink-0 text-[10px] text-fg-muted italic">
                    {MEMORIES_STRINGS.disabledBadge}
                  </span>
                {/if}
              </div>
              <p
                class="memories-index__row-preview mt-0.5 truncate text-xs text-fg-muted"
                data-testid="memories-index-row-preview"
              >
                {row.memory_body_preview}
              </p>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>
