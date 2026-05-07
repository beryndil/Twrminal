<script lang="ts">
  /**
   * ReorgPicker — session picker dialog for ``move_to_session`` and
   * ``split_here`` context-menu actions.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Message bubble"
   * — right-clicking a message and choosing "Move to session…" or
   * "Split here…" opens this dialog.  On confirm the picker calls the
   * appropriate ``reorgStore`` commit method which fires the API, adds
   * the inline ``ReorgAuditDivider``, and starts the 30-second undo
   * toast.
   *
   * Modes:
   *   "move"  — moves the single right-clicked message to the chosen
   *              session via ``POST /api/messages/{id}/move``.
   *   "split" — moves the right-clicked message and all later messages
   *              (by ``seq``) to the chosen session.
   *
   * Inline create form (gap-cycle-10-011):
   *   Clicking "+ Create a new session" flips the dialog body to a
   *   create form (Title + tag chip multi-select).  On submit the form
   *   calls ``createSession()`` then immediately fires the reorg-target
   *   callback against the new session id so both operations complete
   *   in one user gesture.  "Back to list" returns to the session list
   *   without closing the picker.
   *
   * Tag-filter chips (gap-cycle-10-011):
   *   A row of tag chips above the session list narrows candidates when
   *   ≥ 1 chip is selected.  The filter is server-side: selecting a
   *   chip re-fetches ``GET /api/sessions?tag_ids=…`` so only sessions
   *   that carry at least one of the selected tags appear.
   */
  import { createSession, listSessions, type SessionOut } from "../../api/sessions";
  import { listTags, type TagOut } from "../../api/tags";
  import { reorgStore } from "../../stores/reorg.svelte";

  // Picker state is read from the store; open/close is driven externally.
  const pickerState = $derived(reorgStore.picker);

  // ---- Local state --------------------------------------------------------

  let sessions = $state<SessionOut[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);
  let filterText = $state("");
  let selectedId = $state<string | null>(null);
  let committing = $state(false);
  let commitError = $state<string | null>(null);
  let filterEl = $state<HTMLInputElement | null>(null);

  // Source session data captured before filtering (used as defaults in
  // the create form so new sessions inherit working_dir and model).
  let sourceSessionData = $state<SessionOut | null>(null);

  // Tag-filter chips — server-side: selecting a chip re-fetches sessions.
  let allTags = $state<TagOut[]>([]);
  let selectedFilterTagIds = $state(new Set<number>());

  // Inline create form.
  let showCreateForm = $state(false);
  let createTitle = $state("");
  let createTagIds = $state(new Set<number>());
  let creating = $state(false);
  let createError = $state<string | null>(null);
  let createTitleEl = $state<HTMLInputElement | null>(null);

  // ---- Effects ------------------------------------------------------------

  // Focus the filter input on open (list view only).
  $effect(() => {
    if (pickerState !== null && !showCreateForm) {
      setTimeout(() => filterEl?.focus(), 0);
    }
  });

  // Focus the title input when the create form opens.
  $effect(() => {
    if (showCreateForm) {
      setTimeout(() => createTitleEl?.focus(), 0);
    }
  });

  // Session list — re-runs when pickerState or selectedFilterTagIds changes.
  $effect(() => {
    if (pickerState === null) {
      // Picker closed — reset all local state.
      sessions = [];
      filterText = "";
      selectedId = null;
      committing = false;
      commitError = null;
      loadError = null;
      sourceSessionData = null;
      selectedFilterTagIds = new Set();
      showCreateForm = false;
      createTitle = "";
      createTagIds = new Set();
      createError = null;
      return;
    }

    // Spread the Set to register a reactive dependency on its contents.
    const filterArr = [...selectedFilterTagIds];
    const sourceId = pickerState.sourceSessionId;

    loading = true;
    loadError = null;

    const params =
      filterArr.length > 0
        ? { includeClosed: false, tagIds: filterArr }
        : { includeClosed: false };

    void listSessions(params)
      .then((rows) => {
        // Capture source session data before filtering it out so the
        // create form can inherit working_dir and model.
        sourceSessionData = rows.find((s) => s.id === sourceId) ?? null;
        sessions = rows.filter((s) => s.id !== sourceId);
        loading = false;
      })
      .catch((err: unknown) => {
        loadError = err instanceof Error ? err.message : String(err);
        loading = false;
      });
  });

  // Tags — load once when picker opens; clear on close.
  $effect(() => {
    if (pickerState === null) {
      allTags = [];
      return;
    }
    void listTags()
      .then((tags) => {
        allTags = tags;
      })
      .catch(() => {
        // Non-fatal: tag chips simply won't render.
      });
  });

  // ---- Derived -------------------------------------------------------------

  const filteredSessions = $derived.by((): SessionOut[] => {
    const q = filterText.toLowerCase().trim();
    if (q === "") return sessions;
    return sessions.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        (s.description ?? "").toLowerCase().includes(q),
    );
  });

  const dialogTitle = $derived(
    pickerState?.mode === "split" ? "Split conversation here…" : "Move message to session…",
  );
  const confirmLabel = $derived(pickerState?.mode === "split" ? "Split here" : "Move");
  const createSubmitLabel = $derived(
    pickerState?.mode === "split" ? "Create & split" : "Create & move",
  );

  // ---- Actions ------------------------------------------------------------

  function handleCancel(): void {
    reorgStore.closePicker();
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

  function toggleFilterTag(tagId: number): void {
    if (selectedFilterTagIds.has(tagId)) {
      selectedFilterTagIds.delete(tagId);
    } else {
      selectedFilterTagIds.add(tagId);
    }
  }

  function toggleCreateTag(tagId: number): void {
    if (createTagIds.has(tagId)) {
      createTagIds.delete(tagId);
    } else {
      createTagIds.add(tagId);
    }
  }

  async function handleConfirm(): Promise<void> {
    if (pickerState === null || selectedId === null) return;
    const target = sessions.find((s) => s.id === selectedId);
    if (!target) return;

    committing = true;
    commitError = null;
    try {
      if (pickerState.mode === "move") {
        await reorgStore.commitMove(
          pickerState.sourceSessionId,
          pickerState.messageId,
          target.id,
          target.title,
        );
      } else {
        await reorgStore.commitSplit(
          pickerState.sourceSessionId,
          pickerState.messageId,
          pickerState.seq,
          target.id,
          target.title,
        );
      }
      reorgStore.closePicker();
    } catch (err: unknown) {
      commitError = err instanceof Error ? err.message : String(err);
      committing = false;
    }
  }

  async function handleCreateSubmit(): Promise<void> {
    if (pickerState === null || creating) return;
    if (createTitle.trim() === "") {
      createError = "Title is required.";
      return;
    }
    if (createTagIds.size === 0) {
      createError = "Select at least one tag.";
      return;
    }
    creating = true;
    createError = null;
    try {
      const newSession = await createSession({
        kind: "chat",
        title: createTitle.trim(),
        working_dir: sourceSessionData?.working_dir ?? null,
        model: sourceSessionData?.model ?? "claude-sonnet-4-5",
        tag_ids: [...createTagIds],
      });
      if (pickerState.mode === "move") {
        await reorgStore.commitMove(
          pickerState.sourceSessionId,
          pickerState.messageId,
          newSession.id,
          newSession.title,
        );
      } else {
        await reorgStore.commitSplit(
          pickerState.sourceSessionId,
          pickerState.messageId,
          pickerState.seq,
          newSession.id,
          newSession.title,
        );
      }
      reorgStore.closePicker();
    } catch (err: unknown) {
      createError = err instanceof Error ? err.message : String(err);
      creating = false;
    }
  }

  function handleOverlayKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      if (showCreateForm) {
        handleCancelCreate();
      } else {
        handleCancel();
      }
    }
  }
</script>

{#if pickerState !== null}
  <!-- Overlay -->
  <div
    class="rp-overlay"
    role="dialog"
    aria-modal="true"
    aria-label={showCreateForm ? "New session" : dialogTitle}
    tabindex="-1"
    onkeydown={handleOverlayKeydown}
    data-testid="reorg-picker"
    data-mode={pickerState.mode}
  >
    <div class="rp-dialog">
      <!-- Header -->
      <div class="rp-dialog__header">
        <span class="rp-dialog__title">{showCreateForm ? "New session" : dialogTitle}</span>
        <button
          type="button"
          class="rp-dialog__close"
          onclick={handleCancel}
          aria-label="Close picker"
          data-testid="reorg-picker-close"
        >
          ✕
        </button>
      </div>

      {#if showCreateForm}
        <!-- ---- Inline create form ---------------------------------------- -->
        <div class="rp-create-form">
          <label class="rp-create-form__label" for="rp-create-title">Title</label>
          <input
            id="rp-create-title"
            bind:this={createTitleEl}
            type="text"
            class="rp-create-form__input"
            placeholder="Session title…"
            aria-label="New session title"
            bind:value={createTitle}
            data-testid="rp-create-title"
          />
          <div class="rp-create-form__tags-label">Tags <span class="rp-create-form__required">(≥ 1 required)</span></div>
          <div class="rp-tag-chips" data-testid="rp-create-tags">
            {#if allTags.length === 0}
              <span class="rp-list__hint">Loading tags…</span>
            {:else}
              {#each allTags as tag (tag.id)}
                <button
                  type="button"
                  class="rp-chip"
                  class:rp-chip--selected={createTagIds.has(tag.id)}
                  onclick={() => toggleCreateTag(tag.id)}
                  data-testid={`rp-create-tag-${tag.id}`}
                >
                  {tag.name}
                </button>
              {/each}
            {/if}
          </div>
        </div>

        {#if createError !== null}
          <p class="rp-error" role="alert" data-testid="rp-create-error">{createError}</p>
        {/if}

        <div class="rp-dialog__footer">
          <button
            type="button"
            class="rp-btn rp-btn--ghost"
            onclick={handleCancelCreate}
            data-testid="rp-create-cancel"
          >
            Back to list
          </button>
          <button
            type="button"
            class="rp-btn rp-btn--primary"
            disabled={creating}
            onclick={() => void handleCreateSubmit()}
            data-testid="rp-create-submit"
          >
            {creating ? "Creating…" : createSubmitLabel}
          </button>
        </div>
      {:else}
        <!-- ---- Session list view ----------------------------------------- -->

        <!-- Tag-filter chips -->
        {#if allTags.length > 0}
          <div class="rp-tag-filter" data-testid="rp-tag-filter">
            {#each allTags as tag (tag.id)}
              <button
                type="button"
                class="rp-chip"
                class:rp-chip--selected={selectedFilterTagIds.has(tag.id)}
                onclick={() => toggleFilterTag(tag.id)}
                data-testid={`rp-filter-tag-${tag.id}`}
              >
                {tag.name}
              </button>
            {/each}
          </div>
        {/if}

        <!-- Filter input -->
        <input
          bind:this={filterEl}
          type="text"
          class="rp-filter"
          placeholder="Filter sessions…"
          aria-label="Filter sessions"
          bind:value={filterText}
          data-testid="reorg-picker-filter"
        />

        <!-- Session list -->
        <ul
          class="rp-list"
          role="listbox"
          aria-label="Available sessions"
          data-testid="reorg-picker-list"
        >
          {#if loading}
            <li class="rp-list__hint">Loading sessions…</li>
          {:else if loadError !== null}
            <li class="rp-list__error" role="alert">{loadError}</li>
          {:else if filteredSessions.length === 0}
            <li class="rp-list__hint">
              {filterText ? "No sessions match the filter." : "No other sessions available."}
            </li>
          {:else}
            {#each filteredSessions as session (session.id)}
              <li role="option" aria-selected={selectedId === session.id}>
                <button
                  type="button"
                  class="rp-list__item"
                  class:rp-list__item--selected={selectedId === session.id}
                  onclick={() => { selectedId = session.id; }}
                  data-testid={`rp-session-${session.id}`}
                >
                  <span class="rp-list__title">{session.title}</span>
                  {#if session.description}
                    <span class="rp-list__desc">{session.description}</span>
                  {/if}
                </button>
              </li>
            {/each}
          {/if}

          <!-- Create-new affordance always shown at bottom of list -->
          <li>
            <button
              type="button"
              class="rp-list__create"
              onclick={handleOpenCreateForm}
              data-testid="rp-create-new"
            >
              + Create a new session
            </button>
          </li>
        </ul>

        <!-- Commit error -->
        {#if commitError !== null}
          <p class="rp-error" role="alert" data-testid="reorg-picker-error">{commitError}</p>
        {/if}

        <!-- Footer -->
        <div class="rp-dialog__footer">
          <button
            type="button"
            class="rp-btn rp-btn--ghost"
            onclick={handleCancel}
            data-testid="reorg-picker-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            class="rp-btn rp-btn--primary"
            disabled={selectedId === null || committing}
            onclick={() => void handleConfirm()}
            data-testid="reorg-picker-confirm"
          >
            {committing ? "Moving…" : confirmLabel}
          </button>
        </div>
      {/if}
    </div>

    <!-- Backdrop -->
    <button
      type="button"
      class="rp-backdrop"
      onclick={handleCancel}
      aria-label="Close picker"
      tabindex="-1"
    ></button>
  </div>
{/if}

<style>
  .rp-overlay {
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .rp-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    border: none;
    padding: 0;
    cursor: default;
  }

  .rp-dialog {
    position: relative;
    z-index: 201;
    display: flex;
    flex-direction: column;
    background: rgb(var(--bearings-surface-1, var(--bearings-surface-2)));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    width: min(560px, 95vw);
    max-height: min(520px, 90vh);
    overflow: hidden;
  }

  .rp-dialog__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.625rem 0.875rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }

  .rp-dialog__title {
    font-size: 0.875rem;
    font-weight: 600;
  }

  .rp-dialog__close {
    background: none;
    border: none;
    cursor: pointer;
    color: rgb(var(--bearings-fg-muted));
    padding: 0.125rem 0.25rem;
    font-size: 0.875rem;
    line-height: 1;
  }
  .rp-dialog__close:hover {
    color: rgb(var(--bearings-fg));
  }

  /* ---- Tag filter chips (list view) ---- */

  .rp-tag-filter {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    padding: 0.375rem 0.875rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }

  .rp-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.1875rem 0.5rem;
    border-radius: 999px;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-muted));
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .rp-chip:hover {
    background: rgb(var(--bearings-accent) / 0.12);
    color: rgb(var(--bearings-fg));
  }
  .rp-chip--selected {
    background: rgb(var(--bearings-accent) / 0.2);
    border-color: rgb(var(--bearings-accent));
    color: rgb(var(--bearings-fg));
  }

  .rp-filter {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: none;
    border-bottom: 1px solid rgb(var(--bearings-border));
    padding: 0.5rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    outline: none;
    flex-shrink: 0;
  }
  .rp-filter::placeholder {
    color: rgb(var(--bearings-fg-muted));
  }

  .rp-list {
    flex: 1;
    overflow-y: auto;
    list-style: none;
    margin: 0;
    padding: 0.25rem 0;
    min-height: 6rem;
  }

  .rp-list__item {
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
    padding: 0.375rem 0.875rem;
    cursor: pointer;
    width: 100%;
    background: none;
    border: none;
    color: inherit;
    text-align: left;
    font: inherit;
  }
  .rp-list__item:hover,
  .rp-list__item--selected {
    background: rgb(var(--bearings-accent) / 0.15);
  }
  .rp-list__item--selected {
    outline: 1px solid rgb(var(--bearings-accent));
    outline-offset: -1px;
  }

  .rp-list__title {
    font-size: 0.8125rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rp-list__desc {
    font-size: 0.6875rem;
    color: rgb(var(--bearings-fg-muted));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rp-list__hint,
  .rp-list__error {
    padding: 0.5rem 0.875rem;
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
  }
  .rp-list__error {
    color: #f87171;
  }

  .rp-list__create {
    display: block;
    width: 100%;
    padding: 0.375rem 0.875rem;
    background: none;
    border: none;
    border-top: 1px solid rgb(var(--bearings-border));
    color: rgb(var(--bearings-accent));
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    text-align: left;
    margin-top: 0.125rem;
  }
  .rp-list__create:hover {
    background: rgb(var(--bearings-accent) / 0.08);
  }

  /* ---- Inline create form ---- */

  .rp-create-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem 0.875rem;
    flex: 1;
    overflow-y: auto;
  }

  .rp-create-form__label {
    font-size: 0.75rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-muted));
  }

  .rp-create-form__input {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.625rem;
    font: inherit;
    font-size: 0.8125rem;
    outline: none;
  }
  .rp-create-form__input:focus {
    border-color: rgb(var(--bearings-accent));
  }
  .rp-create-form__input::placeholder {
    color: rgb(var(--bearings-fg-muted));
  }

  .rp-create-form__tags-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-muted));
    margin-top: 0.25rem;
  }

  .rp-create-form__required {
    font-weight: 400;
    font-size: 0.6875rem;
  }

  .rp-tag-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }

  .rp-error {
    margin: 0;
    padding: 0.375rem 0.875rem;
    font-size: 0.75rem;
    color: #f87171;
    border-top: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }

  .rp-dialog__footer {
    display: flex;
    justify-content: flex-end;
    gap: 0.375rem;
    padding: 0.5rem 0.875rem;
    border-top: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }

  .rp-btn {
    padding: 0.3125rem 0.75rem;
    border-radius: 0.25rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .rp-btn--ghost {
    background: none;
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
  }
  .rp-btn--ghost:hover {
    background: rgb(var(--bearings-surface-2));
  }
  .rp-btn--primary {
    background: rgb(var(--bearings-accent));
    color: white;
    border: 1px solid transparent;
  }
  .rp-btn--primary:hover {
    opacity: 0.9;
  }
  .rp-btn--primary:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
