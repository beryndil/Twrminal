<script lang="ts">
  import { confirmStore } from '$lib/context-menu/confirm.svelte';

  let remember = $state(false);
  let confirmEl: HTMLButtonElement | undefined = $state();

  // When a new request shows up, reset the remember checkbox and
  // focus the confirm button so keyboard users land on the verb
  // immediately. Destructive flows intentionally *don't* auto-focus
  // the destructive button — users should have to move focus to
  // confirm. We approximate that by focusing the Cancel button for
  // destructive prompts instead.
  let cancelEl: HTMLButtonElement | undefined = $state();

  $effect(() => {
    const req = confirmStore.pending;
    if (!req) return;
    remember = false;
    queueMicrotask(() => {
      if (req.destructive) {
        cancelEl?.focus();
      } else {
        confirmEl?.focus();
      }
    });
  });

  $effect(() => {
    if (!confirmStore.pending) return;
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        confirmStore.dismiss();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  async function onAccept(): Promise<void> {
    await confirmStore.accept(remember);
  }

  function onCancel(): void {
    confirmStore.dismiss();
  }

  function onBackdrop(e: MouseEvent): void {
    // A click directly on the backdrop (not propagated from the
    // dialog surface) dismisses. Matches the undo-toast "click
    // outside" vibe without interfering with text selection inside
    // the dialog itself.
    if (e.target === e.currentTarget) confirmStore.dismiss();
  }
</script>

{#if confirmStore.pending}
  {@const req = confirmStore.pending}
  <div
    role="presentation"
    class="fixed inset-0 z-40 bg-black/60 backdrop-blur-[1px] flex items-center
      justify-center p-4"
    onclick={onBackdrop}
    data-testid="confirm-backdrop"
  >
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      class="rounded border border-slate-700 bg-slate-900 shadow-2xl max-w-md w-full
        p-4 flex flex-col gap-3"
      data-testid="confirm-dialog"
      data-action-id={req.actionId}
    >
      <h2
        id="confirm-dialog-title"
        class="text-sm font-semibold {req.destructive
          ? 'text-rose-300'
          : 'text-slate-200'}"
      >
        {req.message}
      </h2>
      <label class="flex items-center gap-2 text-xs text-slate-400">
        <input
          type="checkbox"
          class="accent-emerald-500"
          bind:checked={remember}
          data-testid="confirm-dont-ask"
        />
        <span>Don't ask again this session</span>
      </label>
      <div class="flex justify-end gap-2 pt-1">
        <button
          bind:this={cancelEl}
          type="button"
          class="px-3 py-1 text-xs rounded border border-slate-700 text-slate-300
            hover:bg-slate-800 disabled:opacity-50"
          onclick={onCancel}
          disabled={confirmStore.busy}
          data-testid="confirm-cancel"
        >
          {req.cancelLabel ?? 'Cancel'}
        </button>
        <button
          bind:this={confirmEl}
          type="button"
          class="px-3 py-1 text-xs rounded font-medium disabled:opacity-50
            {req.destructive
              ? 'bg-rose-700 hover:bg-rose-600 text-white'
              : 'bg-emerald-700 hover:bg-emerald-600 text-white'}"
          onclick={onAccept}
          disabled={confirmStore.busy}
          data-testid="confirm-accept"
        >
          {confirmStore.busy ? '…' : (req.confirmLabel ?? 'Confirm')}
        </button>
      </div>
    </div>
  </div>
{/if}
