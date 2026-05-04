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
  import { goto } from "$app/navigation";

  import {
    SIDEBAR_STRINGS,
    MENU_TARGET_TAG,
    MENU_ACTION_TAG_PIN,
    MENU_ACTION_TAG_UNPIN,
    MENU_ACTION_TAG_COPY_NAME,
    MENU_ACTION_TAG_EDIT,
    MENU_ACTION_TAG_DELETE,
  } from "../../config";
  import type { TagOut } from "../../api/tags";
  import { deleteTag, patchTagPinned } from "../../api/tags";
  import { contextMenu } from "../../actions/contextMenu";
  import { refreshTags } from "../../stores/tags.svelte";
  import ConfirmDialog from "../sidebar/ConfirmDialog.svelte";

  interface Props {
    tags: readonly TagOut[];
    selectedIds: ReadonlySet<number>;
    onToggle: (tagId: number) => void;
    onClear: () => void;
  }

  const { tags, selectedIds, onToggle, onClear }: Props = $props();

  const hasSelection = $derived(selectedIds.size > 0);

  // ---- confirm delete state -----------------------------------------------

  let showDeleteConfirm = $state(false);
  let deletingTag = $state<TagOut | null>(null);

  async function handleDeleteConfirm(): Promise<void> {
    const tag = deletingTag;
    showDeleteConfirm = false;
    deletingTag = null;
    if (tag === null) return;
    try {
      await deleteTag(tag.id);
      await refreshTags();
    } catch {
      // Leave the chip in place — the next refresh shows real state.
    }
  }

  // ---- context menu handlers per tag --------------------------------------

  function menuHandlersForTag(tag: TagOut): Readonly<Record<string, () => void>> {
    return {
      ...(tag.pinned
        ? {
            [MENU_ACTION_TAG_UNPIN]: () => {
              void patchTagPinned(tag.id, false).then(() => refreshTags());
            },
          }
        : {
            [MENU_ACTION_TAG_PIN]: () => {
              void patchTagPinned(tag.id, true).then(() => refreshTags());
            },
          }),
      [MENU_ACTION_TAG_COPY_NAME]: () => {
        void navigator.clipboard.writeText(tag.name);
      },
      [MENU_ACTION_TAG_EDIT]: () => {
        void goto("/tags");
      },
      [MENU_ACTION_TAG_DELETE]: () => {
        deletingTag = tag;
        showDeleteConfirm = true;
      },
    };
  }
</script>

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
    <div class="flex flex-wrap gap-1" role="group" aria-label={SIDEBAR_STRINGS.tagFilterLabel}>
      {#each tags as tag (tag.id)}
        <button
          type="button"
          class="rounded px-1.5 py-0.5 text-xs transition-colors"
          class:bg-accent={selectedIds.has(tag.id)}
          class:text-fg-strong={selectedIds.has(tag.id)}
          class:bg-surface-2={!selectedIds.has(tag.id)}
          class:text-fg-muted={!selectedIds.has(tag.id)}
          aria-pressed={selectedIds.has(tag.id)}
          data-testid="tag-filter-chip"
          data-tag-id={tag.id}
          onclick={() => onToggle(tag.id)}
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
</section>
