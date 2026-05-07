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
   */
  import { listSessions, type SessionOut } from "../../api/sessions";
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

  // Focus the filter input when the picker opens.
  $effect(() => {
    if (pickerState !== null) {
      setTimeout(() => filterEl?.focus(), 0);
    }
  });

  // ---- Session list -------------------------------------------------------

  $effect(() => {
    if (pickerState === null) {
      // Picker closed — clear local state.
      sessions = [];
      filterText = "";
      selectedId = null;
      committing = false;
      commitError = null;
      loadError = null;
      return;
    }
    // Picker just opened — fetch all sessions (including closed).
    loading = true;
    loadError = null;
    void listSessions({ includeClosed: false })
      .then((rows) => {
        // Exclude the source session from the list.
        sessions = rows.filter((s) => s.id !== pickerState.sourceSessionId);
        loading = false;
      })
      .catch((err: unknown) => {
        loadError = err instanceof Error ? err.message : String(err);
        loading = false;
      });
  });

  const filteredSessions = $derived.by((): SessionOut[] => {
    const q = filterText.toLowerCase().trim();
    if (q === "") return sessions;
    return sessions.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        (s.description ?? "").toLowerCase().includes(q),
    );
  });

  // ---- Actions ------------------------------------------------------------

  function handleCancel(): void {
    reorgStore.closePicker();
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

  function handleOverlayKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      handleCancel();
    }
  }

  // ---- Derived labels -----------------------------------------------------

  const dialogTitle = $derived(
    pickerState?.mode === "split" ? "Split conversation here…" : "Move message to session…",
  );
  const confirmLabel = $derived(pickerState?.mode === "split" ? "Split here" : "Move");
</script>

{#if pickerState !== null}
  <!-- Overlay -->
  <div
    class="rp-overlay"
    role="dialog"
    aria-modal="true"
    aria-label={dialogTitle}
    tabindex="-1"
    onkeydown={handleOverlayKeydown}
    data-testid="reorg-picker"
    data-mode={pickerState.mode}
  >
    <div class="rp-dialog">
      <!-- Header -->
      <div class="rp-dialog__header">
        <span class="rp-dialog__title">{dialogTitle}</span>
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
    max-height: min(480px, 90vh);
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
