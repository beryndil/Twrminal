<script lang="ts">
  /**
   * Session picker modal — opened by the "Merge into…" context-menu
   * action on a session row (gap-cycle-03-008).
   *
   * Fetches the current session list on open (excluding the source
   * session), displays them in a scrollable list, and calls
   * :func:`mergeSession` on confirmation. On success calls ``onMerged``
   * with the destination session id so the caller can navigate.
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Session merge" —
   * ``session.merge_into`` "Opens session picker."
   *
   * Inline create form (gap-cycle-10-011):
   *   Clicking "+ Create a new session" flips the modal body to an
   *   inline create form (Title + tag chip multi-select).  On submit
   *   the form calls ``createSession()`` then immediately fires
   *   ``mergeSession()`` against the new id so both operations complete
   *   in one user gesture.  "Back to list" returns to the session list
   *   without closing the modal.
   */
  import { createSession, listSessions } from "../../api/sessions";
  import type { SessionOut } from "../../api/sessions";
  import { listTags, type TagOut } from "../../api/tags";
  import { mergeSession } from "../../api/reorg";
  import { SESSION_PICKER_STRINGS } from "../../config";

  interface Props {
    /** The session being merged (excluded from the picker list). */
    srcSession: SessionOut;
    /** Called with the destination session id after a successful merge. */
    onMerged: (dstSessionId: string) => void;
    /** Called when the user cancels without merging. */
    onCancel: () => void;
  }

  const { srcSession, onMerged, onCancel }: Props = $props();

  let sessions = $state<SessionOut[]>([]);
  let allTags = $state<TagOut[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let merging = $state(false);
  let mergeError = $state<string | null>(null);
  let searchQuery = $state("");

  // Inline create form.
  let showCreateForm = $state(false);
  let createTitle = $state("");
  let createTagIds = $state(new Set<number>());
  let creating = $state(false);
  let createError = $state<string | null>(null);
  let createTitleEl = $state<HTMLInputElement | null>(null);

  // Fetch sessions and tags on mount.
  $effect(() => {
    void (async () => {
      loading = true;
      error = null;
      try {
        const [all, tags] = await Promise.all([listSessions(), listTags()]);
        sessions = all.filter((s) => s.id !== srcSession.id);
        allTags = tags;
      } catch (err) {
        error = err instanceof Error ? err.message : String(err);
      } finally {
        loading = false;
      }
    })();
  });

  // Focus the title input when the create form opens.
  $effect(() => {
    if (showCreateForm) {
      setTimeout(() => createTitleEl?.focus(), 0);
    }
  });

  const filteredSessions = $derived(
    searchQuery.trim() === ""
      ? sessions
      : sessions.filter((s) => s.title.toLowerCase().includes(searchQuery.trim().toLowerCase())),
  );

  async function handleSelect(dst: SessionOut): Promise<void> {
    if (merging) return;
    merging = true;
    mergeError = null;
    try {
      await mergeSession(srcSession.id, dst.id);
      onMerged(dst.id);
    } catch (err) {
      mergeError = err instanceof Error ? err.message : String(err);
      merging = false;
    }
  }

  function handleOpenCreateForm(): void {
    showCreateForm = true;
    createTitle = "";
    createTagIds = new Set();
    createError = null;
  }

  function handleCancelCreate(): void {
    showCreateForm = false;
  }

  function toggleCreateTag(tagId: number): void {
    if (createTagIds.has(tagId)) {
      createTagIds.delete(tagId);
    } else {
      createTagIds.add(tagId);
    }
  }

  async function handleCreateSubmit(): Promise<void> {
    if (creating) return;
    if (createTitle.trim() === "") {
      createError = SESSION_PICKER_STRINGS.createTitleRequired;
      return;
    }
    if (createTagIds.size === 0) {
      createError = SESSION_PICKER_STRINGS.createTagRequired;
      return;
    }
    creating = true;
    createError = null;
    try {
      const newSession = await createSession({
        kind: "chat",
        title: createTitle.trim(),
        working_dir: srcSession.working_dir,
        model: srcSession.model,
        tag_ids: [...createTagIds],
      });
      await mergeSession(srcSession.id, newSession.id);
      onMerged(newSession.id);
    } catch (err) {
      createError = err instanceof Error ? err.message : String(err);
      creating = false;
    }
  }

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (showCreateForm) {
        handleCancelCreate();
      } else {
        onCancel();
      }
    }
  }
</script>

<div
  class="session-picker-backdrop"
  role="presentation"
  data-testid="session-picker-backdrop"
  onclick={onCancel}
  onkeydown={handleKeyDown}
>
  <div
    class="session-picker-modal"
    role="dialog"
    aria-modal="true"
    aria-label={showCreateForm
      ? SESSION_PICKER_STRINGS.createFormTitle
      : SESSION_PICKER_STRINGS.mergePickerTitle}
    tabindex="-1"
    data-testid="session-picker-modal"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    {#if showCreateForm}
      <!-- ---- Inline create form ------------------------------------------ -->
      <header class="session-picker-modal__header">
        <h2 class="session-picker-modal__title" data-testid="session-picker-title">
          {SESSION_PICKER_STRINGS.createFormTitle}
        </h2>
      </header>

      <div class="session-picker-modal__create-body">
        <label class="session-picker-modal__create-label" for="spm-create-title">Title</label>
        <input
          id="spm-create-title"
          bind:this={createTitleEl}
          type="text"
          class="session-picker-modal__create-input"
          placeholder={SESSION_PICKER_STRINGS.createTitlePlaceholder}
          aria-label="New session title"
          bind:value={createTitle}
          data-testid="session-picker-create-title"
        />

        <div class="session-picker-modal__create-tags-label">
          {SESSION_PICKER_STRINGS.createTagsHint}
        </div>
        <div class="session-picker-modal__tag-chips" data-testid="session-picker-create-tags">
          {#if allTags.length === 0}
            <span class="session-picker-modal__status">Loading tags…</span>
          {:else}
            {#each allTags as tag (tag.id)}
              <button
                type="button"
                class="session-picker-modal__chip"
                class:session-picker-modal__chip--selected={createTagIds.has(tag.id)}
                onclick={() => toggleCreateTag(tag.id)}
                data-testid={`session-picker-create-tag-${tag.id}`}
              >
                {tag.name}
              </button>
            {/each}
          {/if}
        </div>
      </div>

      {#if createError !== null}
        <p
          class="session-picker-modal__error"
          role="alert"
          data-testid="session-picker-create-error"
        >
          {createError}
        </p>
      {/if}

      <footer class="session-picker-modal__footer session-picker-modal__footer--split">
        <button
          type="button"
          class="session-picker-modal__btn session-picker-modal__btn--cancel"
          data-testid="session-picker-create-cancel"
          onclick={handleCancelCreate}
        >
          {SESSION_PICKER_STRINGS.createCancelLabel}
        </button>
        <button
          type="button"
          class="session-picker-modal__btn session-picker-modal__btn--primary"
          data-testid="session-picker-create-submit"
          disabled={creating}
          onclick={() => void handleCreateSubmit()}
        >
          {creating ? "Creating…" : SESSION_PICKER_STRINGS.createSubmitLabel}
        </button>
      </footer>
    {:else}
      <!-- ---- Session list view ------------------------------------------- -->
      <header class="session-picker-modal__header">
        <h2 class="session-picker-modal__title" data-testid="session-picker-title">
          {SESSION_PICKER_STRINGS.mergePickerTitle}
        </h2>
        <p class="session-picker-modal__subtitle">
          {SESSION_PICKER_STRINGS.mergePickerSubtitle(srcSession.title)}
        </p>
      </header>

      <div class="session-picker-modal__search">
        <input
          type="text"
          class="session-picker-modal__search-input"
          placeholder={SESSION_PICKER_STRINGS.mergePickerSearchPlaceholder}
          bind:value={searchQuery}
          data-testid="session-picker-search"
          aria-label={SESSION_PICKER_STRINGS.mergePickerSearchPlaceholder}
        />
      </div>

      {#if mergeError !== null}
        <p class="session-picker-modal__error" data-testid="session-picker-merge-error">
          {mergeError}
        </p>
      {/if}

      <div class="session-picker-modal__list" data-testid="session-picker-list">
        {#if loading}
          <p class="session-picker-modal__status">{SESSION_PICKER_STRINGS.mergePickerLoading}</p>
        {:else if error !== null}
          <p class="session-picker-modal__error">{error}</p>
        {:else if filteredSessions.length === 0}
          <p class="session-picker-modal__status">{SESSION_PICKER_STRINGS.mergePickerEmpty}</p>
        {:else}
          {#each filteredSessions as dst (dst.id)}
            <button
              type="button"
              class="session-picker-modal__row"
              data-testid="session-picker-row"
              data-session-id={dst.id}
              disabled={merging}
              onclick={() => void handleSelect(dst)}
            >
              <span class="session-picker-modal__row-title">{dst.title}</span>
              {#if dst.message_count > 0}
                <span class="session-picker-modal__row-count">
                  {dst.message_count}
                  {SESSION_PICKER_STRINGS.mergePickerMsgCount}
                </span>
              {/if}
            </button>
          {/each}
        {/if}
      </div>

      <footer class="session-picker-modal__footer session-picker-modal__footer--split">
        <button
          type="button"
          class="session-picker-modal__btn session-picker-modal__btn--cancel"
          data-testid="session-picker-cancel"
          onclick={onCancel}
        >
          {SESSION_PICKER_STRINGS.mergePickerCancel}
        </button>
        <button
          type="button"
          class="session-picker-modal__btn session-picker-modal__btn--create"
          data-testid="session-picker-create-new"
          onclick={handleOpenCreateForm}
        >
          {SESSION_PICKER_STRINGS.createNewLabel}
        </button>
      </footer>
    {/if}
  </div>
</div>

<style>
  .session-picker-backdrop {
    position: fixed;
    inset: 0;
    background-color: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 900;
  }

  .session-picker-modal {
    background: var(--color-surface-1);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
    display: flex;
    flex-direction: column;
    gap: 0;
    min-width: 340px;
    max-width: 480px;
    width: 100%;
    max-height: 70vh;
    overflow: hidden;
  }

  .session-picker-modal__header {
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--color-border);
  }

  .session-picker-modal__title {
    margin: 0 0 4px;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--color-fg-strong);
  }

  .session-picker-modal__subtitle {
    margin: 0;
    font-size: 0.8rem;
    color: var(--color-fg-muted);
  }

  .session-picker-modal__search {
    padding: 10px 16px;
    border-bottom: 1px solid var(--color-border);
  }

  .session-picker-modal__search-input {
    width: 100%;
    background: var(--color-surface-2);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 0.85rem;
    color: var(--color-fg);
    outline: none;
  }

  .session-picker-modal__search-input:focus {
    border-color: var(--color-accent);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 25%, transparent);
  }

  .session-picker-modal__list {
    flex: 1;
    overflow-y: auto;
    padding: 6px 0;
  }

  .session-picker-modal__row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    width: 100%;
    padding: 8px 20px;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    color: var(--color-fg);
    font-size: 0.875rem;
    transition: background-color 0.1s;
  }

  .session-picker-modal__row:hover:not(:disabled) {
    background: var(--color-surface-2);
  }

  .session-picker-modal__row:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .session-picker-modal__row-title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .session-picker-modal__row-count {
    flex-shrink: 0;
    font-size: 0.75rem;
    color: var(--color-fg-muted);
  }

  .session-picker-modal__status {
    padding: 16px 20px;
    font-size: 0.85rem;
    color: var(--color-fg-muted);
    margin: 0;
  }

  .session-picker-modal__error {
    padding: 8px 16px;
    font-size: 0.8rem;
    color: var(--color-red-400, #f87171);
    margin: 0;
  }

  .session-picker-modal__footer {
    padding: 10px 16px;
    border-top: 1px solid var(--color-border);
    display: flex;
    justify-content: flex-end;
  }

  .session-picker-modal__footer--split {
    justify-content: space-between;
  }

  .session-picker-modal__btn--cancel {
    background: none;
    border: 1px solid var(--color-border);
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 0.85rem;
    cursor: pointer;
    color: var(--color-fg);
    transition: background-color 0.1s;
  }

  .session-picker-modal__btn--cancel:hover {
    background: var(--color-surface-2);
  }

  .session-picker-modal__btn--create {
    background: none;
    border: none;
    padding: 6px 0;
    font-size: 0.85rem;
    cursor: pointer;
    color: var(--color-accent);
  }

  .session-picker-modal__btn--create:hover {
    text-decoration: underline;
  }

  .session-picker-modal__btn--primary {
    background: var(--color-accent);
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 0.85rem;
    cursor: pointer;
    color: white;
    transition: opacity 0.1s;
  }

  .session-picker-modal__btn--primary:hover {
    opacity: 0.9;
  }

  .session-picker-modal__btn--primary:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* ---- Inline create form ---- */

  .session-picker-modal__create-body {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px 20px;
    flex: 1;
    overflow-y: auto;
  }

  .session-picker-modal__create-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--color-fg-muted);
  }

  .session-picker-modal__create-input {
    width: 100%;
    background: var(--color-surface-2);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 0.85rem;
    color: var(--color-fg);
    outline: none;
  }

  .session-picker-modal__create-input:focus {
    border-color: var(--color-accent);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 25%, transparent);
  }

  .session-picker-modal__create-tags-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--color-fg-muted);
    margin-top: 4px;
  }

  .session-picker-modal__tag-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .session-picker-modal__chip {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 999px;
    border: 1px solid var(--color-border);
    background: var(--color-surface-2);
    color: var(--color-fg-muted);
    font-size: 0.75rem;
    cursor: pointer;
    transition:
      background-color 0.1s,
      color 0.1s;
  }

  .session-picker-modal__chip:hover {
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
    color: var(--color-fg);
  }

  .session-picker-modal__chip--selected {
    background: color-mix(in srgb, var(--color-accent) 20%, transparent);
    border-color: var(--color-accent);
    color: var(--color-fg);
  }
</style>
