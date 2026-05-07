<script lang="ts">
  /**
   * MemoriesEditor — per-tag CRUD over user-authored system-prompt
   * fragments (item 2.10; arch §1.1.3 — "tag memories as
   * system-prompt fragments that the prompt assembler reads per
   * turn"). Memories are different from the read-only vault: they
   * ARE editable.
   *
   * Renders:
   *
   * 1. A tag selector (drives :func:`setActiveTag`).
   * 2. A list of memories under the active tag — each row shows
   *    title + enabled toggle + Edit / Delete actions.
   * 3. A single create / edit form panel; the form is the same
   *    layout for both modes, swapping the submit handler.
   *
   * Validation mirrors the backend (TagMemoryIn): title ∈ [1, 200]
   * chars, body ∈ [1, 30 000] chars. The form blocks submit on
   * client-side error so a 422 is unreachable through the form path.
   * The validation helpers live in :mod:`./validation` so the unit
   * tests can exercise the rule shape without mounting the component.
   */
  import { onMount, untrack } from "svelte";

  import {
    MEMORIES_STRINGS,
    TAG_MEMORY_BODY_MAX_LENGTH,
    TAG_MEMORY_TITLE_MAX_LENGTH,
  } from "../../config";
  import { isFormValid, validateMemoryForm } from "./validation";
  import {
    createMemoryFor as createMemoryForDefault,
    deleteMemoryFor as deleteMemoryForDefault,
    memoriesStore as memoriesStoreDefault,
    setActiveTag as setActiveTagDefault,
    updateMemoryFor as updateMemoryForDefault,
  } from "../../stores/memories.svelte";
  import {
    refreshTags as refreshTagsDefault,
    tagsStore as tagsStoreDefault,
  } from "../../stores/tags.svelte";
  import type { TagMemoryOut } from "../../api/memories";

  interface Props {
    /**
     * Initially-active tag (e.g. picked from a context-menu deeplink
     * or the global memories index row click).
     * ``null`` shows the picker without a default scope.
     */
    initialTagId?: number | null;
    /**
     * Memory to open in edit mode on first load (gap-cycle-13-007 —
     * the global index row click passes the memory id so the editor
     * lands with that memory pre-selected for editing). Only consumed
     * once; cleared after the memory is found in the loaded list.
     */
    initialMemoryId?: number | null;
    // Test-injectable seams.
    memoriesStore?: typeof memoriesStoreDefault;
    tagsStore?: typeof tagsStoreDefault;
    refreshTags?: typeof refreshTagsDefault;
    setActiveTag?: typeof setActiveTagDefault;
    createMemoryFor?: typeof createMemoryForDefault;
    updateMemoryFor?: typeof updateMemoryForDefault;
    deleteMemoryFor?: typeof deleteMemoryForDefault;
  }

  const {
    initialTagId = null,
    initialMemoryId = null,
    memoriesStore = memoriesStoreDefault,
    tagsStore = tagsStoreDefault,
    refreshTags = refreshTagsDefault,
    setActiveTag = setActiveTagDefault,
    createMemoryFor = createMemoryForDefault,
    updateMemoryFor = updateMemoryForDefault,
    deleteMemoryFor = deleteMemoryForDefault,
  }: Props = $props();

  let editingId = $state<number | "new" | null>(null);
  let formTitle = $state("");
  let formBody = $state("");
  let formEnabled = $state(true);
  let formSubmitting = $state(false);
  // Pending memory id from initialMemoryId — consumed once the memories
  // list has loaded. Cleared to null after startEdit is called.
  // ``untrack`` is required to snapshot the prop at construction time
  // (Svelte 5 runes disallow referencing a reactive prop directly as a
  // ``$state`` initializer — svelte/valid-compile state_referenced_locally).
  let pendingMemoryId = $state<number | null>(untrack(() => initialMemoryId));

  const errors = $derived(validateMemoryForm({ title: formTitle, body: formBody }));
  const valid = $derived(isFormValid(errors));

  // When the memories list loads and we have a pending memory id (from
  // the global index row click), open that memory for editing.
  $effect(() => {
    if (
      pendingMemoryId !== null &&
      !memoriesStore.loading &&
      memoriesStore.memories.length > 0
    ) {
      const target = memoriesStore.memories.find((m) => m.id === pendingMemoryId);
      if (target !== undefined) {
        startEdit(target);
        pendingMemoryId = null;
      }
    }
  });

  function startCreate(): void {
    editingId = "new";
    formTitle = "";
    formBody = "";
    formEnabled = true;
  }

  function startEdit(memory: TagMemoryOut): void {
    editingId = memory.id;
    formTitle = memory.title;
    formBody = memory.body;
    formEnabled = memory.enabled;
  }

  function cancelEdit(): void {
    editingId = null;
    formTitle = "";
    formBody = "";
    formEnabled = true;
  }

  async function handleSubmit(): Promise<void> {
    if (!valid || formSubmitting) return;
    const tagId = memoriesStore.tagId;
    if (tagId === null) return;
    formSubmitting = true;
    try {
      const payload = {
        title: formTitle.trim(),
        body: formBody.trim(),
        enabled: formEnabled,
      };
      if (editingId === "new") {
        await createMemoryFor(tagId, payload);
      } else if (typeof editingId === "number") {
        await updateMemoryFor(editingId, payload);
      }
      cancelEdit();
    } catch {
      // Errors surface via the store's ``error`` field; the form
      // stays open so the user can retry without retyping.
    } finally {
      formSubmitting = false;
    }
  }

  async function handleToggleEnabled(memory: TagMemoryOut): Promise<void> {
    try {
      await updateMemoryFor(memory.id, {
        title: memory.title,
        body: memory.body,
        enabled: !memory.enabled,
      });
    } catch {
      /* swallow — refreshMemories repaints the actual state. */
    }
  }

  async function handleDelete(memory: TagMemoryOut): Promise<void> {
    if (
      typeof window !== "undefined" &&
      typeof window.confirm === "function" &&
      !window.confirm(MEMORIES_STRINGS.deleteConfirmTemplate.replace("{title}", memory.title))
    ) {
      return;
    }
    try {
      await deleteMemoryFor(memory.id);
      if (editingId === memory.id) cancelEdit();
    } catch {
      /* swallow */
    }
  }

  function handleTagChange(value: string): void {
    if (value === "") {
      setActiveTag(null);
      cancelEdit();
      return;
    }
    const id = Number.parseInt(value, 10);
    if (Number.isNaN(id)) return;
    setActiveTag(id);
    cancelEdit();
  }

  onMount(() => {
    void refreshTags();
    if (initialTagId !== null) {
      setActiveTag(initialTagId);
    }
    return () => {
      setActiveTag(null);
    };
  });

  const activeTag = $derived(
    memoriesStore.tagId === null
      ? null
      : (tagsStore.all.find((t) => t.id === memoriesStore.tagId) ?? null),
  );
</script>

<section
  class="memories-editor flex h-full flex-col"
  data-testid="memories-editor"
  aria-label={MEMORIES_STRINGS.paneAriaLabel}
>
  <header class="memories-editor__header border-b border-border p-3">
    <h2 class="text-sm font-semibold text-fg-strong">{MEMORIES_STRINGS.paneHeading}</h2>

    <label class="mt-2 flex flex-col gap-1 text-xs text-fg-muted">
      {MEMORIES_STRINGS.tagSelectorLabel}
      <select
        class="memories-editor__tag-select rounded bg-surface-2 px-2 py-1 text-sm text-fg"
        data-testid="memories-editor-tag-select"
        value={memoriesStore.tagId === null ? "" : String(memoriesStore.tagId)}
        onchange={(event) => handleTagChange((event.target as HTMLSelectElement).value)}
      >
        <option value="">{MEMORIES_STRINGS.tagSelectorPlaceholder}</option>
        {#each tagsStore.all as tag (tag.id)}
          <option value={String(tag.id)}>{tag.name}</option>
        {/each}
      </select>
    </label>

    {#if tagsStore.all.length === 0}
      <p class="mt-2 text-xs italic text-fg-muted" data-testid="memories-editor-no-tags">
        {MEMORIES_STRINGS.tagSelectorEmpty}
      </p>
    {/if}
  </header>

  <div class="memories-editor__body flex flex-1 flex-row overflow-hidden">
    <aside
      class="memories-editor__list w-80 overflow-y-auto border-r border-border p-2"
      data-testid="memories-editor-list"
    >
      {#if memoriesStore.tagId === null}
        <p class="text-sm text-fg-muted" data-testid="memories-editor-pick-tag">
          {MEMORIES_STRINGS.pickTagFirst}
        </p>
      {:else if memoriesStore.loading && memoriesStore.memories.length === 0}
        <p class="text-sm text-fg-muted" data-testid="memories-editor-loading">
          {MEMORIES_STRINGS.loading}
        </p>
      {:else if memoriesStore.error !== null && memoriesStore.memories.length === 0}
        <p class="text-sm text-red-400" data-testid="memories-editor-error">
          {MEMORIES_STRINGS.loadFailed}
        </p>
      {:else if memoriesStore.memories.length === 0}
        <p class="text-sm text-fg-muted" data-testid="memories-editor-empty">
          {MEMORIES_STRINGS.emptyForTag}
        </p>
      {:else}
        <ul class="flex flex-col gap-2">
          {#each memoriesStore.memories as memory (memory.id)}
            <li
              class="memories-editor__row rounded border border-border bg-surface-1 p-2"
              data-testid="memories-editor-row"
              data-memory-id={memory.id}
              data-enabled={memory.enabled ? "true" : "false"}
            >
              <div class="flex flex-row items-start justify-between gap-2">
                <button
                  type="button"
                  class="flex-1 truncate text-left text-sm text-fg-strong"
                  data-testid="memories-editor-row-title"
                  onclick={() => startEdit(memory)}
                >
                  {memory.title}
                </button>
                <label class="flex items-center gap-1 text-xs text-fg-muted">
                  <input
                    type="checkbox"
                    class="memories-editor__enabled-toggle"
                    data-testid="memories-editor-enabled-toggle"
                    checked={memory.enabled}
                    onchange={() => handleToggleEnabled(memory)}
                  />
                  {MEMORIES_STRINGS.enabledToggleLabel}
                </label>
              </div>
              <p class="mt-1 truncate text-xs text-fg-muted">{memory.body}</p>
              <div class="mt-2 flex flex-row gap-2">
                <button
                  type="button"
                  class="rounded border border-border bg-surface-2 px-2 py-0.5 text-xs hover:bg-surface-0"
                  data-testid="memories-editor-edit"
                  onclick={() => startEdit(memory)}
                >
                  {MEMORIES_STRINGS.editButtonLabel}
                </button>
                <button
                  type="button"
                  class="rounded border border-red-500/50 bg-red-500/10 px-2 py-0.5 text-xs text-fg hover:bg-red-500/20"
                  data-testid="memories-editor-delete"
                  onclick={() => handleDelete(memory)}
                >
                  {MEMORIES_STRINGS.deleteButtonLabel}
                </button>
              </div>
            </li>
          {/each}
        </ul>
      {/if}

      {#if memoriesStore.tagId !== null}
        <button
          type="button"
          class="memories-editor__new-button mt-3 w-full rounded border border-border bg-surface-2 px-2 py-1 text-sm hover:bg-surface-0"
          data-testid="memories-editor-new"
          onclick={startCreate}
        >
          + {MEMORIES_STRINGS.newButtonLabel}
        </button>
      {/if}
    </aside>

    <div
      class="memories-editor__form flex-1 overflow-y-auto p-4"
      data-testid="memories-editor-form-pane"
    >
      {#if editingId === null}
        <p class="text-sm text-fg-muted">
          {activeTag === null
            ? MEMORIES_STRINGS.pickTagFirst
            : MEMORIES_STRINGS.newButtonLabel + " — pick a memory or click + New."}
        </p>
      {:else}
        <form
          class="flex flex-col gap-3"
          data-testid="memories-editor-form"
          onsubmit={(event) => {
            event.preventDefault();
            void handleSubmit();
          }}
        >
          <label class="flex flex-col gap-1 text-xs text-fg-muted">
            {MEMORIES_STRINGS.titleLabel}
            <input
              type="text"
              class="rounded bg-surface-2 px-2 py-1 text-sm text-fg"
              data-testid="memories-editor-title-input"
              placeholder={MEMORIES_STRINGS.titlePlaceholder}
              maxlength={TAG_MEMORY_TITLE_MAX_LENGTH}
              bind:value={formTitle}
            />
            <span class="text-[10px] text-fg-muted">
              {MEMORIES_STRINGS.characterCountTemplate
                .replace("{used}", String(formTitle.length))
                .replace("{max}", String(TAG_MEMORY_TITLE_MAX_LENGTH))}
            </span>
            {#if errors.title !== null}
              <span class="text-xs text-red-400" data-testid="memories-editor-title-error">
                {errors.title}
              </span>
            {/if}
          </label>

          <label class="flex flex-col gap-1 text-xs text-fg-muted">
            {MEMORIES_STRINGS.bodyLabel}
            <textarea
              class="min-h-[10rem] rounded bg-surface-2 px-2 py-1 text-sm text-fg"
              data-testid="memories-editor-body-input"
              placeholder={MEMORIES_STRINGS.bodyPlaceholder}
              maxlength={TAG_MEMORY_BODY_MAX_LENGTH}
              bind:value={formBody}
            ></textarea>
            <span class="text-[10px] text-fg-muted">
              {MEMORIES_STRINGS.characterCountTemplate
                .replace("{used}", String(formBody.length))
                .replace("{max}", String(TAG_MEMORY_BODY_MAX_LENGTH))}
            </span>
            {#if errors.body !== null}
              <span class="text-xs text-red-400" data-testid="memories-editor-body-error">
                {errors.body}
              </span>
            {/if}
          </label>

          <label class="flex items-center gap-2 text-xs text-fg">
            <input
              type="checkbox"
              data-testid="memories-editor-enabled-input"
              bind:checked={formEnabled}
            />
            {MEMORIES_STRINGS.enabledToggleLabel}
            <span class="text-fg-muted">— {MEMORIES_STRINGS.enabledHelp}</span>
          </label>

          <div class="flex flex-row gap-2">
            <button
              type="submit"
              class="rounded border border-border bg-surface-2 px-3 py-1 text-sm hover:bg-surface-0 disabled:opacity-50"
              data-testid="memories-editor-save"
              disabled={!valid || formSubmitting}
            >
              {MEMORIES_STRINGS.saveButtonLabel}
            </button>
            <button
              type="button"
              class="rounded border border-border bg-surface-2 px-3 py-1 text-sm hover:bg-surface-0"
              data-testid="memories-editor-cancel"
              onclick={cancelEdit}
            >
              {MEMORIES_STRINGS.cancelButtonLabel}
            </button>
          </div>
        </form>
      {/if}
    </div>
  </div>
</section>

<style>
  .memories-editor__body {
    min-height: 0;
  }
</style>
