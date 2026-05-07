<script lang="ts">
  /**
   * ReorgUndoToast — transient bottom-right affordance that appears for
   * ~30 seconds after a successful reorg commit.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Message bubble"
   * — "a transient bottom-right ReorgUndoToast appears for ~30 s
   * offering an Undo affordance that reverses the operation
   * server-side."
   *
   * The toast reads its payload from ``reorgStore.undo``; the store
   * owns the timer.  Clicking "Undo" calls ``reorgStore.undoReorg``;
   * clicking "Dismiss" calls ``reorgStore.dismissUndoToast``.
   */
  import { reorgStore } from "../../stores/reorg.svelte";

  const payload = $derived(reorgStore.undo);

  let undoing = $state(false);
  let undoError = $state<string | null>(null);

  async function handleUndo(): Promise<void> {
    if (payload === null) return;
    undoing = true;
    undoError = null;
    try {
      await reorgStore.undoReorg(payload);
    } catch (err: unknown) {
      undoError = err instanceof Error ? err.message : String(err);
      undoing = false;
    }
  }

  function handleDismiss(): void {
    reorgStore.dismissUndoToast();
  }

  const summaryLabel = $derived.by((): string => {
    if (payload === null) return "";
    const { entry } = payload;
    const verb = entry.kind === "split" ? "Split" : "Moved";
    const n = entry.count === 1 ? "1 message" : `${entry.count} messages`;
    return `${verb} ${n} to "${entry.targetSessionTitle}"`;
  });
</script>

{#if payload !== null}
  <div
    class="rut"
    role="status"
    aria-live="polite"
    data-testid="reorg-undo-toast"
    data-kind={payload.entry.kind}
  >
    <span class="rut__label" data-testid="reorg-undo-toast-label">{summaryLabel}</span>

    {#if undoError !== null}
      <span class="rut__error" role="alert">{undoError}</span>
    {/if}

    <div class="rut__actions">
      <button
        type="button"
        class="rut__btn rut__btn--undo"
        disabled={undoing}
        onclick={() => void handleUndo()}
        data-testid="reorg-undo-toast-undo"
      >
        {undoing ? "Undoing…" : "Undo"}
      </button>
      <button
        type="button"
        class="rut__btn rut__btn--dismiss"
        onclick={handleDismiss}
        data-testid="reorg-undo-toast-dismiss"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  </div>
{/if}

<style>
  .rut {
    position: fixed;
    bottom: 1.25rem;
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
    animation: rut-in 0.18s ease-out;
  }

  @keyframes rut-in {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .rut__label {
    flex: 1;
    color: rgb(var(--bearings-fg));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rut__error {
    font-size: 0.6875rem;
    color: #f87171;
    flex-shrink: 0;
  }

  .rut__actions {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
  }

  .rut__btn {
    background: none;
    border: none;
    cursor: pointer;
    font: inherit;
    border-radius: 0.25rem;
    padding: 0.1875rem 0.5rem;
    font-size: 0.75rem;
  }
  .rut__btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .rut__btn--undo {
    color: rgb(var(--bearings-accent));
    font-weight: 600;
    border: 1px solid rgb(var(--bearings-accent) / 0.4);
  }
  .rut__btn--undo:hover:not(:disabled) {
    background: rgb(var(--bearings-accent) / 0.1);
  }

  .rut__btn--dismiss {
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.6875rem;
    padding: 0.1875rem 0.3125rem;
  }
  .rut__btn--dismiss:hover {
    color: rgb(var(--bearings-fg));
    background: rgb(var(--bearings-surface-2));
  }
</style>
