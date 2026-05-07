<script lang="ts" module>
  import type { ChecklistItemOut } from "../../api/checklists";

  /**
   * Flatten a tree into display rows in (sort_order × parent) order
   * with a depth marker per row. Decided-and-documented: building a
   * flat row list lets the component map each row 1:1 to a ``<li>``
   * with a depth-derived indent, which keeps the keyboard-driven
   * Tab/Shift-Tab behavior reachable without a recursive component.
   *
   * Exported so the unit tests can assert the flatten without mounting
   * the component.
   */
  export interface ChecklistRow {
    item: ChecklistItemOut;
    depth: number;
    isLeaf: boolean;
  }

  export function flattenChecklistTree(
    roots: readonly ChecklistItemOut[],
    childrenByParent: ReadonlyMap<number, ChecklistItemOut[]>,
  ): ChecklistRow[] {
    const out: ChecklistRow[] = [];
    function walk(items: readonly ChecklistItemOut[], depth: number): void {
      for (const item of items) {
        const children = childrenByParent.get(item.id) ?? [];
        out.push({ item, depth, isLeaf: children.length === 0 });
        if (children.length > 0) {
          walk(children, depth + 1);
        }
      }
    }
    walk(roots, 0);
    return out;
  }
</script>

<script lang="ts">
  /**
   * ChecklistView — the main checklist pane.
   *
   * Renders:
   *
   * 1. A header band with :class:`AutoDriverControls`.
   * 2. The item tree as a flat list with depth-based indent (per
   *    behavior/checklists.md §"Item nesting semantics" + §"Drag-
   *    reorder visual feedback").
   * 3. An add-item input (auto-focus on mount per behavior doc).
   *
   * Per ``docs/behavior/checklists.md``:
   *
   * - **Tab / Shift+Tab** on a focused item label nest / un-nest
   *   (calls :func:`indentChecklistItem` / :func:`outdentChecklistItem`).
   * - **Drag-and-drop** reorders. v1 uses vanilla HTML5 drag-and-drop
   *   (no third-party Svelte drag library) — the project carries a
   *   minimal-dependency posture (see ``package.json`` deps), and the
   *   behavior doc's drop semantics (drop-on-row → reparent / drop-
   *   between → re-sort) are short enough to implement directly with
   *   tests covering the move calls. Decision recorded inline per
   *   coding-standards "no inline-rationale-only" decisions.
   * - **Checkbox** on a leaf toggles complete; parents render
   *   disabled (state derived from children).
   * - **Inline edit** of the label commits on blur / Enter.
   *
   * Layer rules: every write helper is injected so unit tests don't
   * monkey-patch the api modules.
   */
  import { onMount } from "svelte";

  import { CHECKLIST_STRINGS, AUTO_DRIVER_STATE_RUNNING } from "../../config";
  import {
    checkChecklistItem as checkItemDefault,
    createChecklistItem as createItemDefault,
    deleteChecklistItem as deleteItemDefault,
    indentChecklistItem as indentItemDefault,
    moveChecklistItem as moveItemDefault,
    outdentChecklistItem as outdentItemDefault,
    uncheckChecklistItem as uncheckItemDefault,
    updateChecklistItem as updateItemDefault,
  } from "../../api/checklists";
  import {
    buildChecklistTree,
    checklistStore as checklistStoreDefault,
    pokeChecklist as pokeChecklistDefault,
    setActiveChecklist as setActiveChecklistDefault,
  } from "../../stores/checklist.svelte";
  import type { SessionOut } from "../../api/sessions";
  import AutoDriverControls from "./AutoDriverControls.svelte";
  import ChecklistChat from "./ChecklistChat.svelte";
  import PairedChatLinkSpawn from "./PairedChatLinkSpawn.svelte";
  import SentinelEvent from "./SentinelEvent.svelte";

  interface Props {
    checklistId: string;
    /** Open chat-kind sessions (for the link-existing picker). */
    availableChats?: readonly SessionOut[];
    /**
     * Callback the row's PairedChatLinkSpawn invokes on chat
     * select — the parent layout uses this to switch the
     * ``activeSessionId`` in :mod:`stores/inspector.svelte.ts`.
     */
    onSelectChat?: (chatSessionId: string) => void;
    // Test-injectable seams.
    checklistStore?: typeof checklistStoreDefault;
    setActiveChecklist?: typeof setActiveChecklistDefault;
    pokeChecklist?: typeof pokeChecklistDefault;
    createItem?: typeof createItemDefault;
    updateItem?: typeof updateItemDefault;
    deleteItem?: typeof deleteItemDefault;
    checkItem?: typeof checkItemDefault;
    uncheckItem?: typeof uncheckItemDefault;
    indentItem?: typeof indentItemDefault;
    outdentItem?: typeof outdentItemDefault;
    moveItem?: typeof moveItemDefault;
  }

  const {
    checklistId,
    availableChats = [],
    onSelectChat = () => {},
    checklistStore = checklistStoreDefault,
    setActiveChecklist = setActiveChecklistDefault,
    pokeChecklist = pokeChecklistDefault,
    createItem = createItemDefault,
    updateItem = updateItemDefault,
    deleteItem = deleteItemDefault,
    checkItem = checkItemDefault,
    uncheckItem = uncheckItemDefault,
    indentItem = indentItemDefault,
    outdentItem = outdentItemDefault,
    moveItem = moveItemDefault,
  }: Props = $props();

  let addInput = $state("");
  let addInputEl: HTMLInputElement | null = $state(null);
  let editingItemId = $state<number | null>(null);
  let editingLabel = $state("");
  let dragItemId = $state<number | null>(null);

  // Drive the active-checklist subscription off the prop. ``$effect``
  // keeps the store in sync with prop changes; un-mount clears the
  // poll loop.
  $effect(() => {
    setActiveChecklist(checklistId);
    return () => {
      setActiveChecklist(null);
    };
  });

  const tree = $derived(buildChecklistTree(checklistStore.items));
  const rows = $derived(flattenChecklistTree(tree.roots, tree.childrenByParent));
  const sortedItemIds = $derived(rows.map((row) => row.item.id));

  function refresh(): void {
    void pokeChecklist(checklistId);
  }

  async function handleAddItem(parentId: number | null): Promise<void> {
    const label = addInput.trim();
    if (label === "") return;
    addInput = "";
    try {
      await createItem(checklistId, { label, parent_item_id: parentId });
      refresh();
      addInputEl?.focus();
    } catch {
      // Errors surface via the store's error field on the next
      // refresh; the input stays cleared so the user can retry.
    }
  }

  function startInlineEdit(itemId: number, label: string): void {
    editingItemId = itemId;
    editingLabel = label;
  }

  async function commitInlineEdit(itemId: number): Promise<void> {
    const label = editingLabel.trim();
    editingItemId = null;
    if (label === "") {
      // Empty label is rejected at the boundary per checklists.md
      // §"Item edit / add / delete / reorder"; cancel inline edit.
      return;
    }
    try {
      await updateItem(itemId, { label });
      refresh();
    } catch {
      // Stale item / 422 — the next refresh paints the actual state.
    }
  }

  function cancelInlineEdit(): void {
    editingItemId = null;
  }

  async function handleToggleCheck(row: ChecklistRow): Promise<void> {
    if (!row.isLeaf) return;
    try {
      if (row.item.checked_at !== null) {
        await uncheckItem(row.item.id);
      } else {
        await checkItem(row.item.id);
      }
      refresh();
    } catch {
      /* swallow — refresh shows the actual state. */
    }
  }

  async function handleDelete(itemId: number): Promise<void> {
    if (
      typeof window !== "undefined" &&
      typeof window.confirm === "function" &&
      !window.confirm(CHECKLIST_STRINGS.itemDeleteConfirmTemplate)
    ) {
      return;
    }
    try {
      await deleteItem(itemId);
      refresh();
    } catch {
      /* swallow */
    }
  }

  async function handleKeydownOnLabel(event: KeyboardEvent, row: ChecklistRow): Promise<void> {
    if (event.key === "Tab" && !event.shiftKey) {
      event.preventDefault();
      try {
        await indentItem(row.item.id);
        refresh();
      } catch {
        /* boundary no-op (e.g. first child of its parent). */
      }
    } else if (event.key === "Tab" && event.shiftKey) {
      event.preventDefault();
      try {
        await outdentItem(row.item.id);
        refresh();
      } catch {
        /* root-level no-op. */
      }
    }
  }

  function handleDragStart(itemId: number): void {
    dragItemId = itemId;
  }

  async function handleDrop(targetItemId: number, asChild: boolean): Promise<void> {
    const dragged = dragItemId;
    dragItemId = null;
    if (dragged === null || dragged === targetItemId) return;
    try {
      if (asChild) {
        await moveItem(dragged, { parent_item_id: targetItemId });
      } else {
        // Drop "next to" — pin sort_order one step after the target;
        // the backend's :func:`renumber_siblings` re-spaces if the
        // gap collapses below the configured step.
        const targetItem = checklistStore.items.find((row) => row.id === targetItemId);
        if (targetItem === undefined) return;
        await moveItem(dragged, {
          parent_item_id: targetItem.parent_item_id,
          sort_order: targetItem.sort_order + 1,
        });
      }
      refresh();
    } catch {
      /* swallow — refresh paints actual state. */
    }
  }

  function handleDragOver(event: DragEvent): void {
    // Calling preventDefault on dragover is what enables the drop
    // target per the HTML5 drag-and-drop spec.
    event.preventDefault();
  }

  function isCurrentItem(itemId: number): boolean {
    const run = checklistStore.activeRun;
    if (run === null) return false;
    if (run.state !== AUTO_DRIVER_STATE_RUNNING) return false;
    return run.current_item_id === itemId;
  }

  function isCheckboxChecked(row: ChecklistRow): boolean {
    if (!row.isLeaf) {
      // Parent's checkbox shows AND of children — derive at render time.
      const children = tree.childrenByParent.get(row.item.id) ?? [];
      if (children.length === 0) return row.item.checked_at !== null;
      return children.every((child) => child.checked_at !== null);
    }
    return row.item.checked_at !== null;
  }

  /**
   * Focus the inline-edit input when the {#if} block mounts it. This
   * replaces the bare ``autofocus`` attribute that the Svelte
   * accessibility lint rule (``svelte/no-autofocus``) flags — the
   * action wires the same effect via the explicit lifecycle hook.
   */
  function focusOnMount(node: HTMLInputElement): void {
    node.focus();
  }

  onMount(() => {
    addInputEl?.focus();
  });
</script>

<section
  class="checklist-view flex h-full flex-col"
  data-testid="checklist-view"
  aria-label={CHECKLIST_STRINGS.paneAriaLabel}
>
  <header
    class="checklist-view__header border-b border-border p-3"
    data-testid="checklist-view-header"
  >
    <AutoDriverControls
      {checklistId}
      activeRun={checklistStore.activeRun}
      totalItems={rows.length}
      {sortedItemIds}
      onChange={refresh}
    />
  </header>

  <ChecklistChat {checklistId} />

  <div class="checklist-view__body flex-1 overflow-y-auto p-3" data-testid="checklist-view-body">
    {#if checklistStore.loading}
      <p class="text-sm text-fg-muted" data-testid="checklist-view-loading">
        {CHECKLIST_STRINGS.loadingOverview}
      </p>
    {:else if checklistStore.error !== null}
      <p class="text-sm text-red-400" data-testid="checklist-view-error">
        {CHECKLIST_STRINGS.loadFailed}
      </p>
    {:else if rows.length === 0}
      <p class="text-sm text-fg-muted" data-testid="checklist-view-empty">
        {CHECKLIST_STRINGS.emptyChecklist}
      </p>
    {:else}
      <ul class="checklist-view__items flex flex-col" data-testid="checklist-view-items">
        {#each rows as row (row.item.id)}
          <li
            class="checklist-view__row flex flex-row items-start gap-2 py-1"
            data-testid="checklist-row"
            data-item-id={row.item.id}
            data-depth={row.depth}
            style="padding-left: {row.depth * 1.25}rem"
            draggable="true"
            ondragstart={() => handleDragStart(row.item.id)}
            ondragover={handleDragOver}
            ondrop={(event) => {
              event.preventDefault();
              const asChild = event.shiftKey;
              void handleDrop(row.item.id, asChild);
            }}
          >
            <span
              class="checklist-view__drag-handle cursor-grab text-fg-muted"
              aria-label={CHECKLIST_STRINGS.itemDragHandleAriaLabel}
              data-testid="checklist-drag-handle"
              role="button"
              tabindex="-1">≡</span
            >

            <SentinelEvent item={row.item} isCurrent={isCurrentItem(row.item.id)} />

            <input
              type="checkbox"
              class="checklist-view__checkbox mt-1"
              data-testid="checklist-checkbox"
              checked={isCheckboxChecked(row)}
              disabled={!row.isLeaf}
              title={!row.isLeaf ? CHECKLIST_STRINGS.itemCheckboxParentDisabledTitle : undefined}
              aria-label={CHECKLIST_STRINGS.itemCheckboxAriaLabel}
              onchange={() => handleToggleCheck(row)}
            />

            <div class="checklist-view__row-body flex flex-1 flex-col">
              {#if editingItemId === row.item.id}
                <input
                  type="text"
                  class="checklist-view__label-edit rounded bg-surface-2 px-1 py-0.5 text-sm"
                  data-testid="checklist-label-edit"
                  bind:value={editingLabel}
                  onblur={() => commitInlineEdit(row.item.id)}
                  onkeydown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void commitInlineEdit(row.item.id);
                    } else if (event.key === "Escape") {
                      event.preventDefault();
                      cancelInlineEdit();
                    }
                  }}
                  use:focusOnMount
                />
              {:else}
                <button
                  type="button"
                  class="checklist-view__label text-left text-sm"
                  data-testid="checklist-label"
                  onclick={() => startInlineEdit(row.item.id, row.item.label)}
                  onkeydown={(event) => handleKeydownOnLabel(event, row)}
                >
                  {row.item.label}
                </button>
              {/if}

              <PairedChatLinkSpawn
                item={row.item}
                isLeaf={row.isLeaf}
                {availableChats}
                onChange={refresh}
                {onSelectChat}
              />
            </div>

            <button
              type="button"
              class="checklist-view__delete text-xs text-fg-muted hover:text-red-400"
              data-testid="checklist-delete"
              onclick={() => handleDelete(row.item.id)}
            >
              {CHECKLIST_STRINGS.itemDeleteLabel}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <footer class="checklist-view__footer border-t border-border p-3">
    <input
      type="text"
      class="checklist-view__add-input w-full rounded bg-surface-2 px-2 py-1 text-sm"
      data-testid="checklist-add-input"
      placeholder={CHECKLIST_STRINGS.addItemPlaceholder}
      aria-label={CHECKLIST_STRINGS.addItemAriaLabel}
      bind:this={addInputEl}
      bind:value={addInput}
      onkeydown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          void handleAddItem(null);
        }
      }}
    />
  </footer>
</section>
