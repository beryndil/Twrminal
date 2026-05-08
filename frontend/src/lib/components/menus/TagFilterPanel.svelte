<script lang="ts">
  /**
   * Multi-select tag filter — sits at the top of the sidebar, lists
   * every tag in the system as a chip cluster, and toggles each chip
   * in/out of the active filter set on click.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"creates a chat" — every chat
   *   carries ≥1 tag; the sidebar surfaces those tags so the user
   *   can filter by them.
   * - Master item #537 done-when — "OR semantics across tags". A
   *   session matches when it carries ANY of the selected tags;
   *   selecting more tags WIDENS the result. This is enforced
   *   downstream (the store + backend); the panel's job is the chip
   *   UI + click semantics.
   * - ``docs/behavior/context-menus.md`` §"Tag" — right-click on a
   *   chip opens MENU_TARGET_TAG with pin/unpin/copy/edit/delete
   *   handlers via ``use:contextMenu``.
   *
   * Tags render in alphabetical order (the API contract from
   * :func:`bearings.db.tags.list_all`). Slash-prefix groups
   * (``bearings/architect`` etc.) are not visually grouped at the
   * panel level in v1; they appear as flat chips with the full name.
   * A future tag-group hierarchy view is decided-and-deferred —
   * chat.md is silent on whether the panel groups visually, and the
   * flat list is the simpler floor.
   */
  import { SIDEBAR_STRINGS, MENU_TARGET_TAG } from "../../config";
  import type { TagClass, TagOut } from "../../api/tags";
  import { contextMenu } from "../../actions/contextMenu";
  import { tagsStore, refreshTags, tagsByClass, toggleTagPanel } from "../../stores/tags.svelte";
  import { createTagMenuHandlers, executeTagDelete } from "../../context-menu/actions/tag";
  import ConfirmDialog from "../sidebar/ConfirmDialog.svelte";
  import TagEdit from "./TagEdit.svelte";

  interface Props {
    tags: readonly TagOut[];
    /** Selected project-class tag ids (OR within; AND with other sections). */
    selectedProjectIds: ReadonlySet<number>;
    /** Selected severity-class tag ids (OR within; AND with other sections). */
    selectedSeverityIds: ReadonlySet<number>;
    /** Selected general-class tag ids (OR within; AND with other sections). */
    selectedOtherIds: ReadonlySet<number>;
    /**
     * Whether the synthetic "No severity" chip is active. Composes
     * OR with ``selectedSeverityIds`` within the severity section
     * (gap-cycle-18-003).
     */
    selectedSeverityNone: boolean;
    /**
     * Chip click — flips ``tagId`` in or out of its class section.
     * The class is taken from ``TagOut.class_`` at the click site so
     * the parent doesn't need to look it up.
     */
    onToggle: (tagId: number, klass: TagClass) => void;
    /** Toggle the "No severity" synthetic chip on or off. */
    onToggleSeverityNone: () => void;
    /** Clear button — empties every section. */
    onClear: () => void;
  }

  const {
    tags,
    selectedProjectIds,
    selectedSeverityIds,
    selectedOtherIds,
    selectedSeverityNone,
    onToggle,
    onToggleSeverityNone,
    onClear,
  }: Props = $props();

  const buckets = $derived(tagsByClass(tags));
  const hasSelection = $derived(
    selectedProjectIds.size + selectedSeverityIds.size + selectedOtherIds.size > 0 ||
      selectedSeverityNone,
  );
  const panelCollapsed = $derived(tagsStore.panelCollapsed);
  /** Total count of active filter chips across all sections. */
  const activeCount = $derived(
    selectedProjectIds.size +
      selectedSeverityIds.size +
      selectedOtherIds.size +
      (selectedSeverityNone ? 1 : 0),
  );

  function selectionFor(klass: TagClass): ReadonlySet<number> {
    if (klass === "project") return selectedProjectIds;
    if (klass === "severity") return selectedSeverityIds;
    return selectedOtherIds;
  }

  // ---- confirm delete state -----------------------------------------------

  let showDeleteConfirm = $state(false);
  let deletingTag = $state<TagOut | null>(null);

  async function handleDeleteConfirm(): Promise<void> {
    const tag = deletingTag;
    showDeleteConfirm = false;
    deletingTag = null;
    if (tag === null) return;
    try {
      await executeTagDelete(tag.id);
      await refreshTags();
    } catch {
      // Leave the chip in place — the next refresh shows real state.
    }
  }

  // ---- tag edit modal state -----------------------------------------------

  let editingTag = $state<TagOut | null>(null);

  function handleTagSaved(updated: TagOut): void {
    // Optimistic local update: replace the stale chip data so the chip
    // re-renders immediately with the new class colour without waiting
    // for a full refreshTags() round-trip. The store refresh below keeps
    // truth in sync.
    void refreshTags();
    // Close happens inside TagEdit's onSaved → onClose chain.
    // Suppress unused-warning: `updated` carries the patched row;
    // refreshTags() re-fetches the canonical list so we just trigger it.
    void updated;
  }

  // ---- context menu handlers per tag --------------------------------------

  function menuHandlersForTag(
    tag: TagOut,
  ): Readonly<Record<string, import("../../context-menu/store.svelte").HandlerEntry>> {
    return createTagMenuHandlers(tag, {
      onEdit: (t) => {
        editingTag = t;
      },
      onRequestDelete: (t) => {
        deletingTag = t;
        showDeleteConfirm = true;
      },
      onRefresh: () => refreshTags(),
    });
  }
</script>

{#if editingTag !== null}
  {@const tag = editingTag}
  <TagEdit
    {tag}
    onClose={() => {
      editingTag = null;
    }}
    onSaved={(updated) => {
      handleTagSaved(updated);
      editingTag = null;
    }}
  />
{/if}

{#if showDeleteConfirm && deletingTag !== null}
  <ConfirmDialog
    message={`Delete tag "${deletingTag.name}"? This cannot be undone.`}
    confirmLabel="Delete"
    onConfirm={() => void handleDeleteConfirm()}
    onCancel={() => {
      showDeleteConfirm = false;
      deletingTag = null;
    }}
  />
{/if}

<section
  class="tag-filter border-b border-border px-3 py-2"
  data-testid="tag-filter-panel"
  aria-label={SIDEBAR_STRINGS.tagFilterLabel}
>
  <header class="mb-2 flex items-center justify-between">
    <h2 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {SIDEBAR_STRINGS.tagFilterLabel}
    </h2>
    {#if hasSelection}
      <button
        type="button"
        class="text-xs text-accent hover:underline"
        data-testid="tag-filter-clear"
        onclick={onClear}
      >
        {SIDEBAR_STRINGS.tagFilterClearLabel}
      </button>
    {/if}
  </header>

  <!--
    Chip body — hidden entirely when collapsed so collapsed chips are
    unreachable by keyboard and screen readers. The toggle button's
    ``aria-expanded`` is the primary accessibility signal; ``aria-controls``
    points at the body id when it is in the DOM.
  -->
  {#if !panelCollapsed}
    <div id="tag-filter-chip-body">
      {#if tags.length === 0}
        <p class="text-xs text-fg-muted" data-testid="tag-filter-empty">No tags yet.</p>
      {:else}
        {#each [{ klass: "project" as TagClass, label: "Project", bucket: buckets.project, testid: "tag-filter-section-project" }, { klass: "severity" as TagClass, label: "Severity", bucket: buckets.severity, testid: "tag-filter-section-severity" }, { klass: "general" as TagClass, label: "Other", bucket: buckets.other, testid: "tag-filter-section-other" }] as section (section.klass)}
          <div class="mb-2 last:mb-0" data-testid={section.testid} data-tag-class={section.klass}>
            <h3 class="mb-1 text-[10px] font-semibold uppercase tracking-wider text-fg-muted">
              {section.label}
            </h3>
            {#if section.bucket.length === 0}
              <p class="text-xs text-fg-muted" data-testid={`${section.testid}-empty`}>
                {section.klass === "general"
                  ? "No other tags. Add one on the /tags page."
                  : `No ${section.label.toLowerCase()} tags yet — assign a class on the /tags page.`}
              </p>
            {:else}
              <div class="flex flex-wrap gap-1" role="group" aria-label={`${section.label} tags`}>
                {#each section.bucket as tag, i (tag.id)}
                  {#if i > 0 && !tag.pinned && section.bucket[i - 1].pinned}
                    <div
                      class="my-0.5 w-full border-t border-border/40"
                      role="separator"
                      aria-hidden="true"
                    ></div>
                  {/if}
                  <button
                    type="button"
                    class="rounded px-1.5 py-0.5 text-xs transition-colors"
                    class:bg-accent={selectionFor(section.klass).has(tag.id)}
                    class:text-fg-strong={selectionFor(section.klass).has(tag.id)}
                    class:bg-surface-2={!selectionFor(section.klass).has(tag.id)}
                    class:text-fg-muted={!selectionFor(section.klass).has(tag.id)}
                    aria-pressed={selectionFor(section.klass).has(tag.id)}
                    data-testid="tag-filter-chip"
                    data-tag-id={tag.id}
                    data-tag-class={tag.class_}
                    onclick={() => onToggle(tag.id, section.klass)}
                    use:contextMenu={{
                      target: MENU_TARGET_TAG,
                      handlers: menuHandlersForTag(tag),
                      data: { tagId: tag.id },
                    }}
                  >
                    {tag.name}
                    <span data-testid="tag-filter-chip-counts">
                      <span
                        class="session-count session-count--open"
                        class:text-emerald-500={tag.open_session_count > 0}
                        class:text-fg-muted={tag.open_session_count === 0}
                        >{tag.open_session_count}</span
                      ><span class="session-count text-fg-muted">/{tag.session_count}</span>
                    </span>
                    {#if tag.pinned}
                      <span
                        class="ml-0.5 text-accent"
                        aria-label={SIDEBAR_STRINGS.tagPinnedIndicatorAriaLabel}
                        data-testid="tag-filter-chip-pinned-indicator">★</span
                      >
                    {/if}
                  </button>
                {/each}
                {#if section.klass === "severity"}
                  <!--
                    Synthetic "No severity" chip — surfaces sessions with no
                    severity-class tag (gap-cycle-18-003). Rendered only when
                    the severity section is non-empty so the chip doesn't
                    appear as a lone entry in an otherwise-empty section.
                    Composes OR with selected real severity ids.
                  -->
                  <div
                    class="my-0.5 w-full border-t border-border/40"
                    role="separator"
                    aria-hidden="true"
                  ></div>
                  <button
                    type="button"
                    class="rounded px-1.5 py-0.5 text-xs italic transition-colors"
                    class:bg-accent={selectedSeverityNone}
                    class:text-fg-strong={selectedSeverityNone}
                    class:bg-surface-2={!selectedSeverityNone}
                    class:text-fg-muted={!selectedSeverityNone}
                    aria-pressed={selectedSeverityNone}
                    aria-label={SIDEBAR_STRINGS.tagFilterSeverityNoneAriaLabel}
                    data-testid="tag-filter-chip-severity-none"
                    onclick={onToggleSeverityNone}
                  >
                    {SIDEBAR_STRINGS.tagFilterSeverityNoneLabel}
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      {/if}
    </div>
  {/if}

  <!--
    Footer collapse toggle — always visible so the user can always
    reach the expand affordance without scrolling. Only rendered when
    there are tags to collapse; an empty panel needs no toggle.

    aria-expanded reflects the chip-body visibility; aria-controls
    names the body element when it is present in the DOM.
  -->
  {#if tags.length > 0}
    <footer class="mt-1 flex items-center justify-between">
      <button
        type="button"
        class="flex items-center gap-1 text-xs text-fg-muted hover:text-fg-strong"
        aria-expanded={!panelCollapsed}
        aria-controls="tag-filter-chip-body"
        data-testid="tag-filter-collapse-toggle"
        onclick={toggleTagPanel}
      >
        <span class="select-none transition-transform {panelCollapsed ? '' : 'rotate-90'}">▶</span>
        {panelCollapsed ? SIDEBAR_STRINGS.tagFilterShowLabel : SIDEBAR_STRINGS.tagFilterHideLabel}
      </button>
      {#if panelCollapsed && activeCount > 0}
        <!--
          Compact active-filter breadcrumb: lets the user see filters are
          still applied without expanding the panel.
        -->
        <span
          class="text-xs text-emerald-500"
          data-testid="tag-filter-collapsed-active-count"
          aria-label="{activeCount} filter{activeCount === 1 ? '' : 's'} active"
        >
          {activeCount} on
        </span>
      {/if}
    </footer>
  {/if}
</section>
