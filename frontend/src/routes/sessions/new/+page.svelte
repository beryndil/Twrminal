<script lang="ts">
  /**
   * ``/sessions/new`` route — new-session dialog as a full-page surface.
   *
   * Behavior contract
   * -----------------
   *
   * 1. Renders an inline tags multiselect + working-dir folder picker
   *    above :class:`NewSessionForm`.  The folder picker (item 3.1)
   *    replaces the former plain text input with an interactive
   *    filesystem browser.  The form itself owns the routing axes
   *    selectors, the routing preview, the quota bars, and the
   *    first-message textarea (per its own docstring); this parent
   *    supplies the two fields the form leaves to its host (``tagIds``
   *    + ``workingDir``).
   * 2. On submit:
   *    - Validates ``tagIds.length >= 1`` (the v1 form requires at
   *      least one tag — matches the v0.17 NewSessionForm contract).
   *    - Validates ``workingDir.trim() !== ""`` (the create endpoint
   *      requires a non-empty path).
   *    - Validates ``firstMessage.trim() !== ""`` so the freshly-
   *      created session always has a kick-off prompt — without one
   *      the user lands on an empty conversation that can't be
   *      restarted via Up-arrow.
   *    - POSTs ``/api/sessions`` with the full payload.
   *    - POSTs the first message via :func:`sendPrompt`.
   *    - ``goto(/sessions/<new id>)`` so the URL-driven layout takes
   *      over and the conversation pane fills in.
   *
   * Validation surfaces inline above the submit row; the form itself
   * does not own the error rendering because the form is shared with
   * tests and other potential hosts that may have their own validation.
   *
   * Closing-sweep audit (2026-05-02) — this route was the missing
   * surface that made ``+ New Session`` go nowhere.
   *
   * Item 3.4 (default-from-last-session): on mount the form fetches the
   * most-recently-updated session and pre-fills ``workingDir`` + the
   * initial executor model from it.  Prefs-API defaults (item 3.2) are
   * the fallback when no prior session exists.  Both sources are
   * overridable before the user submits.
   */
  import { goto } from "$app/navigation";
  import { page } from "$app/state";

  import { createSession, getMostRecentSession } from "$lib/api/sessions";
  import { listTags, type TagOut } from "$lib/api/tags";
  import { sendPrompt } from "$lib/api/prompt";
  import { getPreferences } from "$lib/api/preferences";
  import { ApiError } from "$lib/api/client";
  import {
    EXECUTOR_MODEL_SONNET,
    KNOWN_EXECUTOR_MODELS,
    SESSION_KIND_CHAT,
    SESSION_KIND_CHECKLIST,
    type ExecutorModel,
  } from "$lib/config";
  import NewSessionForm, {
    type NewSessionSubmission,
  } from "$lib/components/new_session/NewSessionForm.svelte";
  import FolderPicker from "$lib/components/new_session/FolderPicker.svelte";
  import { contextMenu } from "$lib/actions/contextMenu";
  import {
    MENU_TARGET_TAG_CHIP,
    MENU_ACTION_TAG_CHIP_COPY_NAME,
    MENU_ACTION_TAG_CHIP_DETACH,
  } from "$lib/config";

  /** Title is derived from the first message — single line, ≤80 chars. */
  const TITLE_MAX_FROM_MESSAGE = 80;
  const TITLE_FALLBACK = "(untitled)";
  /** Default title for a freshly-created checklist (no first-message to derive from). */
  const CHECKLIST_TITLE_DEFAULT = "(checklist)";

  let availableTags = $state<TagOut[]>([]);
  let tagsLoading = $state(true);
  let tagsError = $state<string | null>(null);

  let selectedTagIds = $state<number[]>([]);
  let workingDir = $state("");
  // initialExecutor is set from last session (or prefs fallback) on mount.
  let initialExecutor = $state<ExecutorModel>(EXECUTOR_MODEL_SONNET);

  let submitError = $state<string | null>(null);
  let submitting = $state(false);

  // For drag-to-reorder: tracks which tag is being dragged
  let draggedTagId = $state<number | null>(null);

  // Hydrate tags on mount. Session defaults are skipped when the caller
  // passed ``?bare=1`` (Shift+C chord) — the user gets a clean form.
  $effect(() => {
    void hydrateTags();
    if (page.url.searchParams.get("bare") !== "1") {
      void hydrateDefaults();
    }
  });

  // When tags are selected, auto-populate the working dir field from the
  // first (highest-priority) selected tag that has a working_dir set.
  // If the user has manually edited the field, it's not overwritten.
  $effect(() => {
    if (selectedTagIds.length > 0) {
      for (const tagId of selectedTagIds) {
        const tag = availableTags.find((t) => t.id === tagId);
        if (tag?.working_dir && tag.working_dir.trim() !== "") {
          workingDir = tag.working_dir;
          return;
        }
      }
    }
  });

  /**
   * Pre-fill ``workingDir`` + ``initialExecutor`` from the most-recently-
   * updated session (item 3.4).  Falls back to the preferences-API
   * defaults (item 3.2) when no prior session exists.
   */
  async function hydrateDefaults(): Promise<void> {
    // Primary source: most-recent session.
    try {
      const recent = await getMostRecentSession();
      if (recent !== null) {
        if (recent.working_dir.trim() !== "") {
          workingDir = recent.working_dir;
        }
        if ((KNOWN_EXECUTOR_MODELS as readonly string[]).includes(recent.model)) {
          initialExecutor = recent.model as ExecutorModel;
        }
        return;
      }
    } catch {
      // Fall through to preferences.
    }
    // Fallback: preferences-API defaults (3.2).
    try {
      const prefs = await getPreferences();
      if (prefs.default_working_dir != null && prefs.default_working_dir.trim() !== "") {
        workingDir = prefs.default_working_dir;
      }
      if (
        prefs.default_model != null &&
        (KNOWN_EXECUTOR_MODELS as readonly string[]).includes(prefs.default_model)
      ) {
        initialExecutor = prefs.default_model as ExecutorModel;
      }
    } catch {
      // Silently ignore — hardcoded defaults remain.
    }
  }

  async function hydrateTags(): Promise<void> {
    tagsLoading = true;
    tagsError = null;
    try {
      availableTags = await listTags();
    } catch (error) {
      tagsError = error instanceof Error ? error.message : String(error);
    } finally {
      tagsLoading = false;
    }
  }

  function toggleTag(tagId: number): void {
    if (selectedTagIds.includes(tagId)) {
      selectedTagIds = selectedTagIds.filter((id) => id !== tagId);
    } else {
      selectedTagIds = [...selectedTagIds, tagId];
    }
  }

  function handleDragStart(tagId: number): void {
    draggedTagId = tagId;
  }

  function handleDragEnd(): void {
    draggedTagId = null;
  }

  function handleDragOver(e: DragEvent): void {
    e.preventDefault();
    e.dataTransfer!.dropEffect = "move";
  }

  function handleDrop(targetId: number): void {
    if (draggedTagId === null || draggedTagId === targetId) {
      draggedTagId = null;
      return;
    }
    const draggedIndex = selectedTagIds.indexOf(draggedTagId);
    const targetIndex = selectedTagIds.indexOf(targetId);
    if (draggedIndex === -1 || targetIndex === -1) {
      draggedTagId = null;
      return;
    }
    const newIds = [...selectedTagIds];
    newIds.splice(draggedIndex, 1);
    newIds.splice(targetIndex, 0, draggedTagId);
    selectedTagIds = newIds;
    draggedTagId = null;
  }

  /**
   * Pull a sensible session title from the first message: first line,
   * trimmed, capped at :data:`TITLE_MAX_FROM_MESSAGE` characters with a
   * single ``…`` suffix when truncated. The fallback is the database
   * sentinel used by the migration's title-coercion rule.
   */
  function deriveTitle(firstMessage: string): string {
    const firstLine = firstMessage.split(/\r?\n/, 1)[0]?.trim() ?? "";
    if (firstLine === "") {
      return TITLE_FALLBACK;
    }
    if (firstLine.length <= TITLE_MAX_FROM_MESSAGE) {
      return firstLine;
    }
    return `${firstLine.slice(0, TITLE_MAX_FROM_MESSAGE - 1)}…`;
  }

  /**
   * The form's executor selection is the wire model name — pass it
   * straight through to the create endpoint. The DB layer's model
   * validator accepts both the short ids (``sonnet`` / ``haiku`` /
   * ``opus``) and the full ``claude-*`` ids; the form emits the short
   * form so the backend does the right thing.
   */
  function pickModel(executor: ExecutorModel): string {
    return executor;
  }

  async function handleSubmit(payload: NewSessionSubmission): Promise<void> {
    submitError = null;
    if (payload.tagIds.length === 0) {
      submitError = "Attach at least one tag.";
      return;
    }
    const trimmedWd = workingDir.trim();
    if (trimmedWd === "") {
      submitError = "Working dir is required.";
      return;
    }
    if (payload.kind === SESSION_KIND_CHAT) {
      const trimmedMessage = payload.firstMessage.trim();
      if (trimmedMessage === "") {
        submitError = "First message is required.";
        return;
      }
    }
    submitting = true;
    try {
      if (payload.kind === SESSION_KIND_CHECKLIST) {
        // Checklists run no agent and need no first-message kick-off prompt.
        const created = await createSession({
          kind: SESSION_KIND_CHECKLIST,
          title: CHECKLIST_TITLE_DEFAULT,
          working_dir: trimmedWd,
          model: EXECUTOR_MODEL_SONNET,
          tag_ids: payload.tagIds,
        });
        await goto(`/sessions/${encodeURIComponent(created.id)}`);
      } else {
        const trimmedMessage = payload.firstMessage.trim();
        const created = await createSession({
          kind: SESSION_KIND_CHAT,
          title: deriveTitle(payload.firstMessage),
          working_dir: trimmedWd,
          model: pickModel(payload.routing.executor),
          tag_ids: payload.tagIds,
          // Persist the full routing decision so supervisor respawns and
          // mid-session model swaps reconstruct it exactly.
          routing_advisor_model: payload.routing.advisor === "" ? null : payload.routing.advisor,
          routing_advisor_max_uses: payload.routing.advisorMaxUses,
          routing_effort_level: payload.routing.effort,
        });
        // Queue the kick-off prompt against the new session so the
        // first turn is already in flight by the time the URL flips.
        await sendPrompt(created.id, trimmedMessage);
        await goto(`/sessions/${encodeURIComponent(created.id)}`);
      }
    } catch (error) {
      const message = error instanceof ApiError ? describeApiError(error) : String(error);
      submitError = `Couldn't create the session: ${message}`;
    } finally {
      submitting = false;
    }
  }

  function describeApiError(error: ApiError): string {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    return error.message;
  }

  function handleCancel(): void {
    void goto("/");
  }
</script>

<section class="new-session-page" data-testid="new-session-page" aria-label="Create new session">
  <header class="new-session-page__header">
    <h1>Create a new session</h1>
    <p class="new-session-page__lede">
      Pick Chat or Checklist, attach at least one tag, and point at a working directory. Chat
      sessions also require a first message; the routing axes adapt as you type.
    </p>
  </header>

  <fieldset class="new-session-page__tags">
    <legend>Tags — drag selected tags to set priority (top = highest)</legend>
    {#if tagsLoading}
      <p class="new-session-page__hint">Loading tags…</p>
    {:else if tagsError !== null}
      <p class="new-session-page__error" role="alert">Couldn't load tags: {tagsError}</p>
    {:else if availableTags.length === 0}
      <p class="new-session-page__hint">
        No tags yet. Create one from the Tags page first; the new-session form requires at least
        one.
      </p>
    {:else}
      <div class="new-session-page__tags-container">
        <div class="new-session-page__tags-pool">
          <div class="new-session-page__tags-zone-label">Available tags</div>
          <ul class="new-session-page__tag-list" aria-label="Available tags">
            {#each availableTags.filter((t) => !selectedTagIds.includes(t.id)) as tag (tag.id)}
              <li>
                <button
                  type="button"
                  class="new-session-page__tag-chip"
                  aria-pressed="false"
                  onclick={() => toggleTag(tag.id)}
                  data-testid={`new-session-tag-${tag.id}`}
                  use:contextMenu={{
                    target: MENU_TARGET_TAG_CHIP,
                    disabled: false,
                    handlers: {
                      [MENU_ACTION_TAG_CHIP_COPY_NAME]: () => {
                        void navigator.clipboard.writeText(tag.name);
                      },
                    },
                    data: { tagId: tag.id },
                  }}
                >
                  {tag.name}
                </button>
              </li>
            {/each}
          </ul>
        </div>

        <div class="new-session-page__tags-selected">
          <div class="new-session-page__tags-zone-label">Selected (drag to reorder)</div>
          {#if selectedTagIds.length === 0}
            <p class="new-session-page__hint">Click tags above to select them</p>
          {:else}
            <ul class="new-session-page__tag-list-ordered" aria-label="Selected tags">
              {#each selectedTagIds as tagId (tagId)}
                {@const tag = availableTags.find((t) => t.id === tagId)}
                {#if tag}
                  <li
                    draggable="true"
                    ondragstart={() => handleDragStart(tagId)}
                    ondragend={handleDragEnd}
                    ondragover={handleDragOver}
                    ondrop={() => handleDrop(tagId)}
                    class="new-session-page__tag-row"
                    class:new-session-page__tag-row--dragging={draggedTagId === tagId}
                  >
                    <span class="new-session-page__drag-handle" title="Drag to reorder">⠿</span>
                    <button
                      type="button"
                      class="new-session-page__tag-chip new-session-page__tag-chip--active"
                      aria-pressed="true"
                      onclick={() => toggleTag(tagId)}
                      data-testid={`new-session-tag-${tagId}`}
                      use:contextMenu={{
                        target: MENU_TARGET_TAG_CHIP,
                        disabled: false,
                        handlers: {
                          [MENU_ACTION_TAG_CHIP_COPY_NAME]: () => {
                            void navigator.clipboard.writeText(tag.name);
                          },
                          [MENU_ACTION_TAG_CHIP_DETACH]: () => {
                            toggleTag(tagId);
                          },
                        },
                        data: { tagId },
                      }}
                    >
                      {tag.name}
                    </button>
                  </li>
                {/if}
              {/each}
            </ul>
          {/if}
        </div>
      </div>
    {/if}
  </fieldset>

  <div class="new-session-page__field">
    <span>Working directory</span>
    <FolderPicker
      value={workingDir}
      onchange={(path) => {
        workingDir = path;
      }}
    />
  </div>

  <NewSessionForm
    tagIds={selectedTagIds}
    {workingDir}
    {initialExecutor}
    onSubmit={(payload) => {
      void handleSubmit(payload);
    }}
    onCancel={handleCancel}
  />

  {#if submitError !== null}
    <p class="new-session-page__error" role="alert" data-testid="new-session-submit-error">
      {submitError}
    </p>
  {/if}
  {#if submitting}
    <p class="new-session-page__hint" data-testid="new-session-submitting">Creating session…</p>
  {/if}
</section>

<style>
  .new-session-page {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    max-width: 44rem;
    margin: 0 auto;
  }
  .new-session-page__header h1 {
    font-size: 1.25rem;
    font-weight: 600;
    margin: 0;
  }
  .new-session-page__lede {
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0.25rem 0 0 0;
  }
  .new-session-page__tags {
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    padding: 0.5rem 0.75rem;
  }
  .new-session-page__tags legend {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
    padding: 0 0.25rem;
  }
  .new-session-page__tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .new-session-page__tag-chip {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 999px;
    padding: 0.125rem 0.625rem;
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .new-session-page__tag-chip--active {
    background: rgb(var(--bearings-accent));
    color: white;
    border-color: transparent;
  }
  .new-session-page__tags-container {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-top: 0.5rem;
  }
  .new-session-page__tags-pool,
  .new-session-page__tags-selected {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .new-session-page__tags-zone-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
  }
  .new-session-page__tag-list-ordered {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .new-session-page__tag-row {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    opacity: 1;
    transition: opacity 150ms ease-in-out;
  }
  .new-session-page__tag-row--dragging {
    opacity: 0.5;
  }
  .new-session-page__drag-handle {
    flex-shrink: 0;
    width: 1rem;
    height: 1rem;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    cursor: grab;
    user-select: none;
  }
  .new-session-page__tag-row:active .new-session-page__drag-handle {
    cursor: grabbing;
  }
  .new-session-page__field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8125rem;
  }
  .new-session-page__field span {
    color: rgb(var(--bearings-fg-muted));
  }
  .new-session-page__hint {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .new-session-page__error {
    font-size: 0.8125rem;
    color: #f87171;
    margin: 0;
  }
</style>
