<script lang="ts">
  import { onDestroy } from 'svelte';

  import { undoStore, type UndoItem } from '$lib/context-menu/undo.svelte';

  // Generic one-row renderer for the queued undo system (plan §6.8).
  // The host (`UndoToastHost`) owns the stack; this component draws
  // a single item and runs its own countdown / inverse flow. Mirrors
  // the existing `ReorgUndoToast` visually so the two can coexist
  // without the user noticing a seam.

  type Props = {
    item: UndoItem;
  };

  const { item }: Props = $props();

  const startedAt = Date.now();
  let nowMs = $state(startedAt);
  let undoing = $state(false);

  // Visible counter derives from `nowMs` + the live `item.windowMs`.
  // The store's own timer drives auto-dismiss; this interval only
  // updates the displayed seconds-remaining.
  const remaining = $derived(
    Math.max(0, Math.ceil((item.windowMs - (nowMs - startedAt)) / 1000))
  );

  const tick = setInterval(() => {
    nowMs = Date.now();
  }, 250);

  onDestroy(() => clearInterval(tick));

  async function runUndo(): Promise<void> {
    if (undoing) return;
    undoing = true;
    try {
      await undoStore.invoke(item.id);
    } finally {
      undoing = false;
    }
  }

  function dismiss(): void {
    undoStore.dismiss(item.id);
  }
</script>

<div
  class="rounded-lg border border-slate-700 bg-slate-900 shadow-2xl px-4 py-3
    flex flex-col gap-2 max-w-sm pointer-events-auto"
  role="status"
  aria-live="polite"
  data-testid="undo-toast"
  data-undo-id={item.id}
>
  {#if item.detail}
    <p
      class="text-[11px] text-amber-300 border border-amber-500/40 bg-amber-500/10
        rounded px-2 py-1"
      data-testid="undo-toast-detail"
    >
      {item.detail}
    </p>
  {/if}
  <div class="flex items-center gap-3">
    <span class="text-xs text-slate-200 flex-1">
      {item.message}
    </span>
    <button
      type="button"
      class="text-xs text-amber-300 hover:text-amber-200 font-medium disabled:opacity-50"
      onclick={runUndo}
      disabled={undoing}
      data-testid="undo-toast-button"
    >
      {undoing ? 'Undoing…' : `Undo (${remaining}s)`}
    </button>
    <button
      type="button"
      class="text-slate-500 hover:text-slate-300 text-xs"
      aria-label="Dismiss undo toast"
      onclick={dismiss}
    >
      ✕
    </button>
  </div>
</div>
