<script lang="ts">
  /**
   * SessionEdit modal — allows editing Title, Description, Budget cap,
   * Tags, and Session instructions for an existing session.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"SessionEdit modal" — full field set,
   *   PATCH /api/sessions/{id} wire contract, Cancel / Esc / backdrop
   *   semantics, and tag inline-create UX.
   * - ``docs/behavior/context-menus.md`` §"Session row" — the
   *   ``session.edit`` context-menu action opens this modal seeded from
   *   the right-clicked row.
   *
   * **Out of scope**: AI-title-suggestion (✨). That feature depends on
   * the absent anthropic backend (cycle 1 gap-020 root cause). The ✨
   * button is not rendered; see ``docs/behavior/chat.md`` §"SessionEdit
   * modal — deferred features" for the documented carve-out.
   */
  import { untrack } from "svelte";
  import { patchSession, type SessionOut } from "../../api/sessions";
  import { attachTagToSession, createTag, type TagOut } from "../../api/tags";
  import { contextMenu } from "../../actions/contextMenu";
  import {
    MENU_ACTION_TAG_CHIP_COPY_NAME,
    MENU_ACTION_TAG_CHIP_DETACH,
    MENU_TARGET_TAG_CHIP,
    SESSION_EDIT_MODAL_STRINGS,
    UNDO_TOAST_STRINGS,
  } from "../../config";
  import { undoStore } from "../../stores/undo.svelte";

  interface Props {
    session: SessionOut;
    /** Tags currently attached to this session. */
    currentTags: readonly TagOut[];
    /** All tags in the system — seeded before the modal opens. */
    allTags: readonly TagOut[];
    /**
     * Called with the saved session after a successful PATCH so the
     * parent can update local state / trigger a store refresh.
     */
    onSave: (updated: SessionOut) => void;
    onCancel: () => void;
    /**
     * When true the modal scrolls to and focuses the Session instructions
     * textarea on mount — used by InspectorInstructions "Edit…" button.
     */
    focusInstructions?: boolean;
  }

  const {
    session,
    currentTags,
    allTags,
    onSave,
    onCancel,
    focusInstructions = false,
  }: Props = $props();

  // ---- field state -------------------------------------------------------
  // Use untrack() to capture the initial prop values without reactively
  // tracking them — this modal is open-once-per-edit, so seeding from
  // the snapshot at open time is the correct behaviour.

  let titleValue = $state(untrack(() => session.title));
  let descriptionValue = $state(untrack(() => session.description ?? ""));
  let budgetValue = $state(
    untrack(() => (session.max_budget_usd !== null ? String(session.max_budget_usd) : "")),
  );
  let instructionsValue = $state(untrack(() => session.session_instructions ?? ""));

  // ---- tag state ---------------------------------------------------------

  /**
   * Working set of tags attached in this editing session — initialised
   * from ``currentTags`` then mutated as the user adds / removes chips.
   */
  let attachedTags = $state<TagOut[]>(untrack(() => [...currentTags]));

  /** Controlled value of the tag text input. */
  let tagInput = $state("");

  /** Whether the suggestion dropdown is open. */
  let showSuggestions = $state(false);

  /**
   * Tags from ``allTags`` that match the current ``tagInput`` prefix and
   * are not already attached.
   */
  const tagSuggestions = $derived(
    tagInput.trim().length === 0
      ? []
      : allTags.filter(
          (t) =>
            t.name.toLowerCase().includes(tagInput.trim().toLowerCase()) &&
            !attachedTags.some((a) => a.id === t.id),
        ),
  );

  /** True when the trimmed input doesn't match any existing tag name exactly. */
  const canCreateTag = $derived(
    tagInput.trim().length > 0 &&
      !allTags.some((t) => t.name.toLowerCase() === tagInput.trim().toLowerCase()),
  );

  function removeTag(tagId: number): void {
    attachedTags = attachedTags.filter((t) => t.id !== tagId);
  }

  function selectSuggestion(tag: TagOut): void {
    attachedTags = [...attachedTags, tag];
    tagInput = "";
    showSuggestions = false;
  }

  // ---- save state --------------------------------------------------------

  let saving = $state(false);
  let errorMsg = $state<string | null>(null);

  // ---- focus-instructions ref -------------------------------------------

  let instructionsEl = $state<HTMLTextAreaElement | null>(null);

  $effect(() => {
    if (focusInstructions && instructionsEl !== null) {
      instructionsEl.scrollIntoView({ block: "center" });
      instructionsEl.focus();
    }
  });

  // ---- save --------------------------------------------------------------

  async function handleSave(): Promise<void> {
    const trimmedTitle = titleValue.trim();
    if (!trimmedTitle) {
      errorMsg = "Title cannot be empty";
      return;
    }

    saving = true;
    errorMsg = null;

    try {
      // Parse budget: empty string → null (no cap), otherwise parse float.
      let budgetUsd: number | null = null;
      const budgetTrimmed = budgetValue.trim();
      if (budgetTrimmed !== "") {
        const parsed = parseFloat(budgetTrimmed);
        if (isNaN(parsed) || parsed < 0) {
          errorMsg = "Budget must be a non-negative number or blank";
          saving = false;
          return;
        }
        budgetUsd = parsed;
      }

      const updated = await patchSession(session.id, {
        title: trimmedTitle,
        description: descriptionValue.trim() === "" ? null : descriptionValue.trim(),
        max_budget_usd: budgetUsd,
        session_instructions: instructionsValue.trim() === "" ? null : instructionsValue.trim(),
        tag_ids: attachedTags.map((t) => t.id),
      });

      onSave(updated);
    } catch (err) {
      errorMsg = `${SESSION_EDIT_MODAL_STRINGS.errorPrefix} ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      saving = false;
    }
  }

  // ---- tag creation (inline) ---------------------------------------------

  async function handleTagInputKeydown(event: KeyboardEvent): Promise<void> {
    if (event.key === "Escape") {
      // Let the backdrop handler close the modal.
      tagInput = "";
      showSuggestions = false;
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const name = tagInput.trim();
      if (!name) return;

      const exact = allTags.find((t) => t.name.toLowerCase() === name.toLowerCase());
      if (exact) {
        if (!attachedTags.some((a) => a.id === exact.id)) {
          // Attach existing tag via the API then add to local state.
          try {
            await attachTagToSession(session.id, exact.id);
            attachedTags = [...attachedTags, exact];
          } catch {
            // Non-fatal; leave the tag unattached and let the final save fix it.
            attachedTags = [...attachedTags, exact];
          }
        }
        tagInput = "";
        showSuggestions = false;
        return;
      }

      // Create-and-attach a new tag inline.
      try {
        const newTag = await createTag({ name });
        attachedTags = [...attachedTags, newTag];
      } catch (err) {
        errorMsg = `${SESSION_EDIT_MODAL_STRINGS.errorPrefix} ${err instanceof Error ? err.message : String(err)}`;
      }
      tagInput = "";
      showSuggestions = false;
    }
  }

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
    }
  }
</script>

<div
  class="session-edit-backdrop"
  role="presentation"
  data-testid="session-edit-backdrop"
  onclick={onCancel}
  onkeydown={handleKeyDown}
>
  <div
    class="session-edit-modal"
    role="dialog"
    aria-modal="true"
    aria-label={SESSION_EDIT_MODAL_STRINGS.ariaLabel}
    tabindex="-1"
    data-testid="session-edit-modal"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <h2 class="session-edit-modal__title" data-testid="session-edit-title">
      {SESSION_EDIT_MODAL_STRINGS.title}
    </h2>

    <!-- Title -->
    <div class="session-edit-modal__field">
      <label for="session-edit-title-input" class="session-edit-modal__label">
        {SESSION_EDIT_MODAL_STRINGS.titleLabel}
      </label>
      <input
        id="session-edit-title-input"
        type="text"
        class="session-edit-modal__input"
        data-testid="session-edit-title-input"
        bind:value={titleValue}
        disabled={saving}
        placeholder={SESSION_EDIT_MODAL_STRINGS.titlePlaceholder}
      />
    </div>

    <!-- Description -->
    <div class="session-edit-modal__field">
      <label for="session-edit-description-input" class="session-edit-modal__label">
        {SESSION_EDIT_MODAL_STRINGS.descriptionLabel}
      </label>
      <textarea
        id="session-edit-description-input"
        class="session-edit-modal__textarea"
        data-testid="session-edit-description-input"
        bind:value={descriptionValue}
        disabled={saving}
        placeholder={SESSION_EDIT_MODAL_STRINGS.descriptionPlaceholder}
        rows={3}
      ></textarea>
    </div>

    <!-- Budget cap -->
    <div class="session-edit-modal__field">
      <label for="session-edit-budget-input" class="session-edit-modal__label">
        {SESSION_EDIT_MODAL_STRINGS.budgetLabel}
      </label>
      <input
        id="session-edit-budget-input"
        type="number"
        min="0"
        step="0.01"
        class="session-edit-modal__input session-edit-modal__input--narrow"
        data-testid="session-edit-budget-input"
        bind:value={budgetValue}
        disabled={saving}
        placeholder={SESSION_EDIT_MODAL_STRINGS.budgetPlaceholder}
      />
    </div>

    <!-- Tags -->
    <div class="session-edit-modal__field">
      <span class="session-edit-modal__label" id="session-edit-tags-label">
        {SESSION_EDIT_MODAL_STRINGS.tagsLabel}
      </span>
      <div class="session-edit-modal__tags" data-testid="session-edit-tags">
        {#each attachedTags as tag (tag.id)}
          <span
            class="session-edit-modal__tag-chip"
            data-testid="session-edit-tag-chip"
            data-tag-id={tag.id}
            use:contextMenu={{
              target: MENU_TARGET_TAG_CHIP,
              handlers: {
                [MENU_ACTION_TAG_CHIP_COPY_NAME]: () => {
                  void navigator.clipboard.writeText(tag.name);
                },
                [MENU_ACTION_TAG_CHIP_DETACH]: {
                  handler: () => {
                    removeTag(tag.id);
                    undoStore.push({
                      message: UNDO_TOAST_STRINGS.tagRemoved,
                      inverse: () => {
                        attachedTags = [...attachedTags, tag];
                      },
                    });
                  },
                  confirmMessage: `Remove tag "${tag.name}" from session?`,
                  confirmLabel: "Remove",
                },
              },
              data: { tagId: tag.id, sessionId: session.id },
            }}
          >
            {tag.name}
            <button
              type="button"
              class="session-edit-modal__tag-remove"
              aria-label={`Remove tag ${tag.name}`}
              data-testid="session-edit-tag-remove"
              disabled={saving}
              onclick={() => removeTag(tag.id)}
            >×</button>
          </span>
        {/each}
        <div class="session-edit-modal__tag-input-wrap">
          <input
            type="text"
            class="session-edit-modal__tag-input"
            data-testid="session-edit-tag-input"
            aria-labelledby="session-edit-tags-label"
            bind:value={tagInput}
            disabled={saving}
            placeholder={SESSION_EDIT_MODAL_STRINGS.tagInputPlaceholder}
            oninput={() => {
              showSuggestions = tagInput.trim().length > 0;
            }}
            onkeydown={(e) => void handleTagInputKeydown(e)}
            onblur={() => {
              // Delay so a suggestion click fires before the list hides.
              setTimeout(() => {
                showSuggestions = false;
              }, 150);
            }}
          />
          {#if showSuggestions && (tagSuggestions.length > 0 || canCreateTag)}
            <ul class="session-edit-modal__suggestions" data-testid="session-edit-tag-suggestions" role="listbox">
              {#each tagSuggestions as suggestion (suggestion.id)}
                <li
                  role="option"
                  aria-selected="false"
                  class="session-edit-modal__suggestion-item"
                  data-testid="session-edit-tag-suggestion"
                  data-tag-id={suggestion.id}
                  onmousedown={(e) => {
                    e.preventDefault();
                    selectSuggestion(suggestion);
                  }}
                >
                  {suggestion.name}
                </li>
              {/each}
              {#if canCreateTag}
                <li
                  role="option"
                  aria-selected="false"
                  class="session-edit-modal__suggestion-item session-edit-modal__suggestion-item--create"
                  data-testid="session-edit-tag-create-hint"
                  onmousedown={(e) => {
                    e.preventDefault();
                    void handleTagInputKeydown(new KeyboardEvent("keydown", { key: "Enter" }));
                  }}
                >
                  {SESSION_EDIT_MODAL_STRINGS.tagCreateHint(tagInput.trim())}
                </li>
              {/if}
            </ul>
          {/if}
        </div>
      </div>
    </div>

    <!-- Session instructions -->
    <div class="session-edit-modal__field">
      <label for="session-edit-instructions-input" class="session-edit-modal__label">
        {SESSION_EDIT_MODAL_STRINGS.instructionsLabel}
      </label>
      <textarea
        id="session-edit-instructions-input"
        class="session-edit-modal__textarea session-edit-modal__textarea--instructions"
        data-testid="session-edit-instructions-input"
        bind:value={instructionsValue}
        bind:this={instructionsEl}
        disabled={saving}
        placeholder={SESSION_EDIT_MODAL_STRINGS.instructionsPlaceholder}
        rows={6}
      ></textarea>
    </div>

    <!-- Error -->
    {#if errorMsg !== null}
      <p class="session-edit-modal__error" data-testid="session-edit-error">{errorMsg}</p>
    {/if}

    <!-- Actions -->
    <div class="session-edit-modal__actions">
      <button
        type="button"
        class="session-edit-modal__btn session-edit-modal__btn--cancel"
        data-testid="session-edit-cancel"
        disabled={saving}
        onclick={onCancel}
      >
        {SESSION_EDIT_MODAL_STRINGS.cancelButton}
      </button>
      <button
        type="button"
        class="session-edit-modal__btn session-edit-modal__btn--save"
        data-testid="session-edit-save"
        disabled={saving}
        onclick={() => void handleSave()}
      >
        {saving ? SESSION_EDIT_MODAL_STRINGS.savingButton : SESSION_EDIT_MODAL_STRINGS.saveButton}
      </button>
    </div>
  </div>
</div>

<style>
  .session-edit-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }

  .session-edit-modal {
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    width: 100%;
    max-width: 36rem;
    max-height: 90vh;
    overflow-y: auto;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .session-edit-modal__title {
    font-size: 0.9375rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }

  .session-edit-modal__field {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .session-edit-modal__label {
    font-size: 0.75rem;
    font-weight: 500;
    color: rgb(var(--bearings-fg-muted));
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .session-edit-modal__input {
    width: 100%;
    background: rgb(var(--bearings-surface-2));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.5rem;
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg-strong));
    outline: none;
    box-sizing: border-box;
  }

  .session-edit-modal__input:focus {
    border-color: rgb(var(--bearings-accent));
    box-shadow: 0 0 0 1px rgb(var(--bearings-accent));
  }

  .session-edit-modal__input--narrow {
    max-width: 12rem;
  }

  .session-edit-modal__textarea {
    width: 100%;
    background: rgb(var(--bearings-surface-2));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.5rem;
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg-strong));
    outline: none;
    resize: vertical;
    font-family: inherit;
    box-sizing: border-box;
  }

  .session-edit-modal__textarea:focus {
    border-color: rgb(var(--bearings-accent));
    box-shadow: 0 0 0 1px rgb(var(--bearings-accent));
  }

  .session-edit-modal__textarea--instructions {
    font-family: monospace;
    font-size: 0.8125rem;
  }

  /* ---- Tags ---- */

  .session-edit-modal__tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    align-items: flex-start;
  }

  .session-edit-modal__tag-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    background: rgb(var(--bearings-surface-2));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.1875rem 0.5rem 0.1875rem 0.625rem;
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg));
  }

  .session-edit-modal__tag-remove {
    background: none;
    border: none;
    cursor: pointer;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.9375rem;
    line-height: 1;
    padding: 0;
    display: flex;
    align-items: center;
  }

  .session-edit-modal__tag-remove:hover:not(:disabled) {
    color: rgb(var(--bearings-fg-strong));
  }

  .session-edit-modal__tag-remove:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .session-edit-modal__tag-input-wrap {
    position: relative;
    flex: 1;
    min-width: 12rem;
  }

  .session-edit-modal__tag-input {
    width: 100%;
    background: rgb(var(--bearings-surface-2));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.25rem 0.5rem;
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg-strong));
    outline: none;
    box-sizing: border-box;
  }

  .session-edit-modal__tag-input:focus {
    border-color: rgb(var(--bearings-accent));
    box-shadow: 0 0 0 1px rgb(var(--bearings-accent));
  }

  .session-edit-modal__suggestions {
    position: absolute;
    top: calc(100% + 2px);
    left: 0;
    right: 0;
    z-index: 10;
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    list-style: none;
    margin: 0;
    padding: 0.25rem 0;
    max-height: 12rem;
    overflow-y: auto;
  }

  .session-edit-modal__suggestion-item {
    padding: 0.3125rem 0.75rem;
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg));
    cursor: pointer;
  }

  .session-edit-modal__suggestion-item:hover {
    background: rgb(var(--bearings-surface-2));
  }

  .session-edit-modal__suggestion-item--create {
    color: rgb(var(--bearings-accent));
    font-style: italic;
  }

  /* ---- Error / actions ---- */

  .session-edit-modal__error {
    font-size: 0.75rem;
    color: #f87171;
    margin: 0;
  }

  .session-edit-modal__actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding-top: 0.25rem;
  }

  .session-edit-modal__btn {
    padding: 0.3125rem 0.875rem;
    border-radius: 0.25rem;
    font-size: 0.875rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .session-edit-modal__btn:hover:not(:disabled) {
    background: rgb(var(--bearings-surface-1));
  }

  .session-edit-modal__btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .session-edit-modal__btn--save {
    background: rgb(var(--bearings-accent));
    color: rgb(var(--bearings-fg-strong));
    border-color: rgb(var(--bearings-accent));
  }

  .session-edit-modal__btn--save:hover:not(:disabled) {
    opacity: 0.85;
  }
</style>
