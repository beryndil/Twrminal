<script lang="ts">
  /**
   * Tag picker for the session context menu "Edit tags…" action.
   *
   * Presents the full tag list with checkboxes; the selected set is
   * initialised from the tags currently attached to the session. On
   * Save, diffs the new set against the old and fires ``PUT`` / ``DELETE``
   * for each change via :func:`attachTagToSession` /
   * :func:`detachTagFromSession`. Closing with Esc or clicking Cancel
   * discards changes.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Session row"
   * — ``session.edit_tags`` "Opens tag picker."
   */
  import { untrack } from "svelte";

  import { attachTagToSession, detachTagFromSession, type TagOut } from "../../api/tags";

  interface Props {
    sessionId: string;
    /** Tags currently attached to this session (from the sessions store). */
    currentTags: readonly TagOut[];
    /** All tags in the system — shown in the picker list. */
    allTags: readonly TagOut[];
    onSave: () => void;
    onCancel: () => void;
  }

  const { sessionId, currentTags, allTags, onSave, onCancel }: Props = $props();

  /** Mutable working set — tag ids the user has toggled in this session. */
  let selected = $state<Set<number>>(untrack(() => new Set(currentTags.map((t) => t.id))));

  let saving = $state(false);
  let errorMsg = $state<string | null>(null);

  function toggle(tagId: number): void {
    const next = new Set(selected);
    if (next.has(tagId)) {
      next.delete(tagId);
    } else {
      next.add(tagId);
    }
    selected = next;
  }

  async function handleSave(): Promise<void> {
    saving = true;
    errorMsg = null;
    const originalIds = new Set(currentTags.map((t) => t.id));
    try {
      // Attach newly selected tags.
      for (const id of selected) {
        if (!originalIds.has(id)) {
          await attachTagToSession(sessionId, id);
        }
      }
      // Detach deselected tags.
      for (const id of originalIds) {
        if (!selected.has(id)) {
          await detachTagFromSession(sessionId, id);
        }
      }
      onSave();
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : String(err);
    } finally {
      saving = false;
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
  class="session-tag-picker-backdrop"
  role="presentation"
  data-testid="session-tag-picker-backdrop"
  onclick={onCancel}
  onkeydown={handleKeyDown}
>
  <div
    class="session-tag-picker"
    data-testid="session-tag-picker"
    role="dialog"
    aria-modal="true"
    aria-label="Edit tags"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <h2 class="session-tag-picker__title">Edit tags</h2>

    {#if allTags.length === 0}
      <p class="session-tag-picker__empty" data-testid="session-tag-picker-empty">
        No tags exist yet.
      </p>
    {:else}
      <ul class="session-tag-picker__list" data-testid="session-tag-picker-list">
        {#each allTags as tag (tag.id)}
          <li class="session-tag-picker__item">
            <label class="session-tag-picker__label" data-testid="session-tag-picker-item">
              <input
                type="checkbox"
                checked={selected.has(tag.id)}
                disabled={saving}
                data-testid="session-tag-picker-checkbox"
                data-tag-id={tag.id}
                onchange={() => toggle(tag.id)}
              />
              <span>{tag.name}</span>
            </label>
          </li>
        {/each}
      </ul>
    {/if}

    {#if errorMsg !== null}
      <p class="session-tag-picker__error" data-testid="session-tag-picker-error">
        {errorMsg}
      </p>
    {/if}

    <div class="session-tag-picker__actions">
      <button
        type="button"
        class="session-tag-picker__btn session-tag-picker__btn--cancel"
        disabled={saving}
        data-testid="session-tag-picker-cancel"
        onclick={onCancel}
      >
        Cancel
      </button>
      <button
        type="button"
        class="session-tag-picker__btn session-tag-picker__btn--save"
        disabled={saving}
        data-testid="session-tag-picker-save"
        onclick={() => void handleSave()}
      >
        {saving ? "Saving…" : "Save"}
      </button>
    </div>
  </div>
</div>

<style>
  .session-tag-picker-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .session-tag-picker {
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    min-width: 18rem;
    max-width: 26rem;
    width: 100%;
    max-height: 80vh;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .session-tag-picker__title {
    font-size: 0.875rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }

  .session-tag-picker__empty {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
  }

  .session-tag-picker__list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .session-tag-picker__label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg));
    cursor: pointer;
    padding: 0.25rem 0.375rem;
    border-radius: 0.25rem;
  }

  .session-tag-picker__label:hover {
    background: rgb(var(--bearings-surface-2));
  }

  .session-tag-picker__error {
    font-size: 0.75rem;
    color: #f87171;
  }

  .session-tag-picker__actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding-top: 0.25rem;
  }

  .session-tag-picker__btn {
    padding: 0.25rem 0.75rem;
    border-radius: 0.25rem;
    font-size: 0.875rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .session-tag-picker__btn:hover:not(:disabled) {
    background: rgb(var(--bearings-surface-1));
  }

  .session-tag-picker__btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .session-tag-picker__btn--save {
    background: rgb(var(--bearings-accent));
    color: rgb(var(--bearings-fg-strong));
    border-color: rgb(var(--bearings-accent));
  }

  .session-tag-picker__btn--save:hover:not(:disabled) {
    opacity: 0.85;
  }
</style>
