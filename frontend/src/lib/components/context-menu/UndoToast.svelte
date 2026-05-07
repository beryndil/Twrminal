<script lang="ts">
  /**
   * General-purpose undo toast — renders the most-recent entry from
   * ``undoStore`` as a transient bottom-right affordance.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md``
   * §"Common behavior — Toast feedback" — "Destructive completions show
   * an undo toast for a few seconds: clicking it reverses the action
   * when the operation is reversible."
   *
   * Positioned at ``bottom: 4.5rem`` so that when ``ReorgUndoToast``
   * (at ``bottom: 1.25rem``) is also visible the two toasts stack
   * vertically rather than overlapping.  They belong to independent
   * domains (general destructive actions vs. reorg moves/splits) and
   * are intentionally rendered by separate components.
   */
  import { undoStore } from "../../stores/undo.svelte";
  import { UNDO_TOAST_STRINGS } from "../../config";

  /** Most-recent stack entry — null when the toast is hidden. */
  const top = $derived(undoStore.stack[0] ?? null);

  let undoing = $state(false);
  let undoError = $state<string | null>(null);

  // Reset local working state whenever the displayed entry changes so
  // stale "Undoing…" labels and inline errors don't bleed across entries.
  $effect(() => {
    void top;
    undoing = false;
    undoError = null;
  });

  async function handleUndo(): Promise<void> {
    if (top === null) return;
    const { id, inverse } = top;
    undoing = true;
    undoError = null;
    try {
      await inverse();
      undoStore.dismiss(id);
    } catch (err: unknown) {
      undoError = err instanceof Error ? err.message : String(err);
      undoing = false;
    }
  }

  function handleDismiss(): void {
    if (top === null) return;
    undoStore.dismiss(top.id);
  }
</script>

{#if top !== null}
  <div
    class="ut"
    role="status"
    aria-live="polite"
    data-testid="undo-toast"
  >
    <span class="ut__label" data-testid="undo-toast-label">{top.message}</span>

    {#if undoError !== null}
      <span class="ut__error" role="alert">{undoError}</span>
    {/if}

    <div class="ut__actions">
      <button
        type="button"
        class="ut__btn ut__btn--undo"
        disabled={undoing}
        onclick={() => void handleUndo()}
        data-testid="undo-toast-undo"
      >
        {undoing ? UNDO_TOAST_STRINGS.undoingLabel : UNDO_TOAST_STRINGS.undoLabel}
      </button>
      <button
        type="button"
        class="ut__btn ut__btn--dismiss"
        onclick={handleDismiss}
        data-testid="undo-toast-dismiss"
        aria-label={UNDO_TOAST_STRINGS.dismissAriaLabel}
      >
        ✕
      </button>
    </div>
  </div>
{/if}

<style>
  .ut {
    position: fixed;
    bottom: 4.5rem;
    right: 1.25rem;
    z-index: 300;
    display: flex;
    align-items: center;
    gap: 0.625rem;
    padding: 0.5rem 0.75rem;
    background: rgb(var(--bearings-surface-1, var(--bearings-surface-2)));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
    font-size: 0.8125rem;
    max-width: min(360px, 90vw);
    animation: ut-in 0.18s ease-out;
  }

  @keyframes ut-in {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .ut__label {
    flex: 1;
    color: rgb(var(--bearings-fg));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ut__error {
    font-size: 0.6875rem;
    color: #f87171;
    flex-shrink: 0;
  }

  .ut__actions {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
  }

  .ut__btn {
    background: none;
    border: none;
    cursor: pointer;
    font: inherit;
    border-radius: 0.25rem;
    padding: 0.1875rem 0.5rem;
    font-size: 0.75rem;
  }

  .ut__btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .ut__btn--undo {
    color: rgb(var(--bearings-accent));
    font-weight: 600;
    border: 1px solid rgb(var(--bearings-accent) / 0.4);
  }

  .ut__btn--undo:hover:not(:disabled) {
    background: rgb(var(--bearings-accent) / 0.1);
  }

  .ut__btn--dismiss {
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.6875rem;
    padding: 0.1875rem 0.3125rem;
  }

  .ut__btn--dismiss:hover {
    color: rgb(var(--bearings-fg));
    background: rgb(var(--bearings-surface-2));
  }
</style>
