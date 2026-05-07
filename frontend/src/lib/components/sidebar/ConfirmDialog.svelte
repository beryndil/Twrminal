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
   *
   * When ``showSuppressCheckbox`` is ``true`` a "Don't ask again this
   * session" checkbox renders below the message. If the user ticks the
   * box and clicks Confirm, ``onConfirmAndSuppress`` is called instead
   * of ``onConfirm``; the caller is responsible for recording the
   * suppression. Cancelling (with or without the box ticked) always
   * calls ``onCancel`` and never triggers suppression.
   *
   * Focus management: when the dialog opens, focus lands on Cancel for
   * destructive actions (so a stray Enter cancels rather than
   * confirming) or on Confirm for non-destructive informational
   * confirms. Focus is queued via ``queueMicrotask`` after Svelte's
   * pending changes to ensure the buttons are mounted. See
   * ``docs/behavior/modals.md`` §"ConfirmDialog focus".
   *
   * Async confirm: ``onConfirm`` (and ``onConfirmAndSuppress``) may
   * return a ``Promise``. While the promise is in flight both buttons
   * are disabled and the Confirm button label flips to
   * ``CONTEXT_MENU_STRINGS.confirmPendingLabel`` ("…") to signal
   * activity. Esc and backdrop-click are also suppressed while pending.
   * On resolve the parent owns closing the dialog (its ``onConfirm``
   * callback is the commit point). On rejection the dialog stays open
   * and surfaces the error message inline below the message. See
   * ``docs/behavior/modals.md`` §"ConfirmDialog async pending".
   */

  import { onMount } from "svelte";

  import { CONTEXT_MENU_STRINGS } from "../../config";

  interface Props {
    /** Short sentence describing the irreversible action. */
    message: string;
    /** Label for the confirm button (default: "Confirm"). */
    confirmLabel?: string;
    /**
     * When ``true`` (default), focus lands on Cancel on open so a stray
     * Enter cancels rather than confirming. When ``false`` (informational
     * confirms), focus lands on Confirm for faster keyboard-confirm
     * without mouse travel.
     */
    destructive?: boolean;
    /**
     * When ``true``, a "Don't ask again this session" checkbox renders
     * below the message. Defaults to ``false`` for backwards
     * compatibility with callers that manage their own suppress logic.
     */
    showSuppressCheckbox?: boolean;
    /**
     * May return a ``Promise`` for async operations. While the promise is
     * in flight the dialog enters its pending state (buttons disabled,
     * Confirm label flips to "…"). On resolve the parent owns close; on
     * rejection the dialog stays open with an inline error.
     */
    onConfirm: () => void | Promise<void>;
    /**
     * Called instead of ``onConfirm`` when the user ticks the suppress
     * checkbox and clicks Confirm. Only invoked when
     * ``showSuppressCheckbox`` is ``true`` and the box is checked.
     * Falls back to ``onConfirm`` when not provided. May return a
     * ``Promise`` for the same async-pending semantics as ``onConfirm``.
     */
    onConfirmAndSuppress?: () => void | Promise<void>;
    onCancel: () => void;
  }

  const {
    message,
    confirmLabel = "Confirm",
    destructive = true,
    showSuppressCheckbox = false,
    onConfirm,
    onConfirmAndSuppress,
    onCancel,
  }: Props = $props();

  let cancelBtn = $state<HTMLButtonElement | null>(null);
  let confirmBtn = $state<HTMLButtonElement | null>(null);
  let pending = $state(false);
  let errorMsg = $state<string | null>(null);

  onMount(() => {
    queueMicrotask(() => {
      (destructive ? cancelBtn : confirmBtn)?.focus();
    });
  });

  let dontAskAgain = $state(false);

  async function handleConfirm(): Promise<void> {
    pending = true;
    errorMsg = null;
    try {
      if (showSuppressCheckbox && dontAskAgain && onConfirmAndSuppress !== undefined) {
        await onConfirmAndSuppress();
      } else {
        await onConfirm();
      }
    } catch (err: unknown) {
      errorMsg =
        err instanceof Error ? err.message : CONTEXT_MENU_STRINGS.confirmErrorFallback;
    } finally {
      pending = false;
    }
  }

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !pending) {
      event.stopPropagation();
      onCancel();
    }
  }
</script>

<div
  class="confirm-dialog-backdrop"
  role="presentation"
  data-testid="confirm-dialog-backdrop"
  onclick={() => { if (!pending) onCancel(); }}
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
    {#if showSuppressCheckbox}
      <label class="confirm-dialog__suppress" data-testid="confirm-dialog-suppress-label">
        <input
          type="checkbox"
          class="confirm-dialog__suppress-checkbox"
          data-testid="confirm-dialog-suppress-checkbox"
          bind:checked={dontAskAgain}
        />
        {CONTEXT_MENU_STRINGS.confirmSuppressCheckboxLabel}
      </label>
    {/if}
    {#if errorMsg !== null}
      <p
        class="confirm-dialog__error"
        role="alert"
        data-testid="confirm-dialog-error"
      >{errorMsg}</p>
    {/if}
    <div class="confirm-dialog__actions">
      <button
        type="button"
        class="confirm-dialog__btn confirm-dialog__btn--cancel"
        data-testid="confirm-dialog-cancel"
        bind:this={cancelBtn}
        disabled={pending}
        onclick={onCancel}
      >
        Cancel
      </button>
      <button
        type="button"
        class="confirm-dialog__btn confirm-dialog__btn--confirm"
        data-testid="confirm-dialog-confirm"
        bind:this={confirmBtn}
        disabled={pending}
        onclick={handleConfirm}
      >
        {pending ? CONTEXT_MENU_STRINGS.confirmPendingLabel : confirmLabel}
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

  .confirm-dialog__suppress {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    cursor: pointer;
    user-select: none;
  }

  .confirm-dialog__suppress-checkbox {
    cursor: pointer;
    accent-color: rgb(var(--bearings-accent, 99 102 241));
  }

  .confirm-dialog__error {
    font-size: 0.8125rem;
    color: #f87171;
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

  .confirm-dialog__btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
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
