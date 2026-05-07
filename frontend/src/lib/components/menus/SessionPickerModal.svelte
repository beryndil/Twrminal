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
   */
  import { listSessions } from "../../api/sessions";
  import type { SessionOut } from "../../api/sessions";
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
  let loading = $state(true);
  let error = $state<string | null>(null);
  let merging = $state(false);
  let mergeError = $state<string | null>(null);
  let searchQuery = $state("");

  // Fetch sessions on mount.
  $effect(() => {
    void (async () => {
      loading = true;
      error = null;
      try {
        const all = await listSessions();
        // Exclude the source session from the picker.
        sessions = all.filter((s) => s.id !== srcSession.id);
      } catch (err) {
        error = err instanceof Error ? err.message : String(err);
      } finally {
        loading = false;
      }
    })();
  });

  const filteredSessions = $derived(
    searchQuery.trim() === ""
      ? sessions
      : sessions.filter((s) =>
          s.title.toLowerCase().includes(searchQuery.trim().toLowerCase()),
        ),
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

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
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
    aria-label={SESSION_PICKER_STRINGS.mergePickerTitle}
    tabindex="-1"
    data-testid="session-picker-modal"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
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

    <footer class="session-picker-modal__footer">
      <button
        type="button"
        class="session-picker-modal__btn session-picker-modal__btn--cancel"
        data-testid="session-picker-cancel"
        onclick={onCancel}
      >
        {SESSION_PICKER_STRINGS.mergePickerCancel}
      </button>
    </footer>
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
</style>
