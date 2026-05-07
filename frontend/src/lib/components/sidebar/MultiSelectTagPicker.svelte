<script lang="ts">
  /**
   * Tag picker for multi-select "Add tag" / "Remove tag" actions.
   *
   * Clicking a tag immediately applies it to every session in the
   * selection and closes the picker — no explicit Save step.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md``
   * §"Multi-select" — "The submenu arrows (▸) on Add tag / Remove tag
   * open lists of tags currently in the user's tag set; selecting one
   * applies it to every selected session."
   *
   * Mode ``add``: shows all available tags.
   * Mode ``remove``: shows only tags common to ALL selected sessions.
   */
  import type { TagOut } from "../../api/tags";
  import { bulkTagSessions, bulkUntagSessions } from "../../api/sessionsBulk";

  interface Props {
    /** Determines whether the action is an attach or detach. */
    mode: "add" | "remove";
    /** Tag list to present (caller pre-filters for "remove" mode). */
    tags: readonly TagOut[];
    /** Session IDs to apply the action to. */
    selectedSessionIds: ReadonlySet<string>;
    /** Called after the tag is successfully applied to all sessions. */
    onDone: () => void;
    onCancel: () => void;
  }

  const { mode, tags, selectedSessionIds, onDone, onCancel }: Props = $props();

  let working = $state(false);
  let errorMsg = $state<string | null>(null);

  const title = $derived(
    mode === "add" ? "Add tag to selected sessions" : "Remove tag from selected sessions",
  );

  async function applyTag(tagId: number): Promise<void> {
    working = true;
    errorMsg = null;
    try {
      const ids = Array.from(selectedSessionIds);
      const result =
        mode === "add"
          ? await bulkTagSessions(ids, tagId)
          : await bulkUntagSessions(ids, tagId);
      const failed = result.results.filter((r) => !r.ok);
      if (failed.length > 0) {
        const details = failed
          .map((r) => r.detail ?? "unknown error")
          .slice(0, 3)
          .join("; ");
        const suffix = failed.length > 3 ? ` (+${failed.length - 3} more)` : "";
        errorMsg = `${failed.length} failed: ${details}${suffix}`;
        working = false;
        return;
      }
      onDone();
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : String(err);
      working = false;
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
  class="multi-tag-picker-backdrop"
  role="presentation"
  data-testid="multi-tag-picker-backdrop"
  onclick={onCancel}
  onkeydown={handleKeyDown}
>
  <div
    class="multi-tag-picker"
    role="dialog"
    aria-modal="true"
    aria-label={title}
    tabindex="-1"
    data-testid="multi-tag-picker"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <h2 class="multi-tag-picker__title" data-testid="multi-tag-picker-title">{title}</h2>

    {#if tags.length === 0}
      <p class="multi-tag-picker__empty" data-testid="multi-tag-picker-empty">
        {mode === "remove" ? "No common tags to remove." : "No tags exist yet."}
      </p>
    {:else}
      <ul class="multi-tag-picker__list" data-testid="multi-tag-picker-list">
        {#each tags as tag (tag.id)}
          <li>
            <button
              type="button"
              class="multi-tag-picker__tag-btn"
              disabled={working}
              data-testid="multi-tag-picker-tag"
              data-tag-id={tag.id}
              onclick={() => void applyTag(tag.id)}
            >
              {tag.name}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if errorMsg !== null}
      <p class="multi-tag-picker__error" data-testid="multi-tag-picker-error">{errorMsg}</p>
    {/if}

    <div class="multi-tag-picker__footer">
      <button
        type="button"
        class="multi-tag-picker__cancel"
        disabled={working}
        data-testid="multi-tag-picker-cancel"
        onclick={onCancel}
      >
        Cancel
      </button>
    </div>
  </div>
</div>

<style>
  .multi-tag-picker-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .multi-tag-picker {
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    min-width: 18rem;
    max-width: 26rem;
    width: 100%;
    max-height: 70vh;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .multi-tag-picker__title {
    font-size: 0.875rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }

  .multi-tag-picker__empty {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }

  .multi-tag-picker__list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }

  .multi-tag-picker__tag-btn {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg));
    background: transparent;
    border: none;
    cursor: pointer;
  }

  .multi-tag-picker__tag-btn:hover:not(:disabled) {
    background: rgb(var(--bearings-surface-2));
  }

  .multi-tag-picker__tag-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .multi-tag-picker__error {
    font-size: 0.75rem;
    color: #f87171;
    margin: 0;
  }

  .multi-tag-picker__footer {
    display: flex;
    justify-content: flex-end;
    padding-top: 0.25rem;
  }

  .multi-tag-picker__cancel {
    padding: 0.25rem 0.75rem;
    border-radius: 0.25rem;
    font-size: 0.875rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .multi-tag-picker__cancel:hover:not(:disabled) {
    background: rgb(var(--bearings-surface-1));
  }

  .multi-tag-picker__cancel:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
