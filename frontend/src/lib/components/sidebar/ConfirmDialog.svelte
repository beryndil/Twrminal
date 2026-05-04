<script lang="ts">
  /**
   * Generic confirmation dialog — used by destructive context-menu
   * actions (e.g. "Delete session") to satisfy the doc requirement
   * that §"Destructive entries" route through a confirm dialog.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Common
   * behavior" — "Destructive entries. Actions in the ``destructive``
   * section route through a confirmation dialog before firing. The
   * dialog states what is about to happen and offers Cancel / Confirm.
   * The user's confirm action is the commit point; closing the dialog
   * with Esc cancels."
   */

  interface Props {
    /** Short sentence describing the irreversible action. */
    message: string;
    /** Label for the confirm button (default: "Confirm"). */
    confirmLabel?: string;
    onConfirm: () => void;
    onCancel: () => void;
  }

  const { message, confirmLabel = "Confirm", onConfirm, onCancel }: Props = $props();

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
    }
  }
</script>

<div
  class="confirm-dialog-backdrop"
  role="presentation"
  data-testid="confirm-dialog-backdrop"
  onclick={onCancel}
  onkeydown={handleKeyDown}
>
  <div
    class="confirm-dialog"
    role="alertdialog"
    aria-modal="true"
    aria-label="Confirm action"
    tabindex="-1"
    data-testid="confirm-dialog"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <p class="confirm-dialog__message" data-testid="confirm-dialog-message">{message}</p>
    <div class="confirm-dialog__actions">
      <button
        type="button"
        class="confirm-dialog__btn confirm-dialog__btn--cancel"
        data-testid="confirm-dialog-cancel"
        onclick={onCancel}
      >
        Cancel
      </button>
      <button
        type="button"
        class="confirm-dialog__btn confirm-dialog__btn--confirm"
        data-testid="confirm-dialog-confirm"
        onclick={onConfirm}
      >
        {confirmLabel}
      </button>
    </div>
  </div>
</div>

<style>
  .confirm-dialog-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .confirm-dialog {
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    min-width: 18rem;
    max-width: 26rem;
    width: 100%;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .confirm-dialog__message {
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg));
    margin: 0;
  }

  .confirm-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }

  .confirm-dialog__btn {
    padding: 0.25rem 0.75rem;
    border-radius: 0.25rem;
    font-size: 0.875rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .confirm-dialog__btn:hover {
    background: rgb(var(--bearings-surface-1));
  }

  .confirm-dialog__btn--confirm {
    background: #ef4444;
    color: #fff;
    border-color: #ef4444;
  }

  .confirm-dialog__btn--confirm:hover {
    background: #dc2626;
    border-color: #dc2626;
  }
</style>
