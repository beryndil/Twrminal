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
  import {
    SIDEBAR_STRINGS,
    MENU_TARGET_TAG,
  } from "../../config";
  import type { TagClass, TagOut } from "../../api/tags";
  import { contextMenu } from "../../actions/contextMenu";
  import { refreshTags, tagsByClass } from "../../stores/tags.svelte";
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
     * Chip click — flips ``tagId`` in or out of its class section.
     * The class is taken from ``TagOut.class_`` at the click site so
     * the parent doesn't need to look it up.
     */
    onToggle: (tagId: number, klass: TagClass) => void;
    /** Clear button — empties every section. */
    onClear: () => void;
  }

  const {
    tags,
    selectedProjectIds,
    selectedSeverityIds,
    selectedOtherIds,
    onToggle,
    onClear,
  }: Props = $props();

  const buckets = $derived(tagsByClass(tags));
  const hasSelection = $derived(
    selectedProjectIds.size + selectedSeverityIds.size + selectedOtherIds.size > 0,
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

  function menuHandlersForTag(tag: TagOut): Readonly<Record<string, import("../../context-menu/store.svelte").HandlerEntry>> {
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
            {#each section.bucket as tag (tag.id)}
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
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  {/if}
</section>
