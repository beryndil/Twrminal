<script lang="ts">
  import { stubStore, type StubItem } from '$lib/context-menu/stub.svelte';

  // Single stub-toast row. Stores a generated "actionId" tag + reason
  // for the "not yet implemented" signal. Unlike UndoToast there is
  // no interactive button — these are advisory, so dismissal is
  // purely an × or the auto-timeout owned by the store.

  type Props = {
    item: StubItem;
  };

  const { item }: Props = $props();
</script>

<div
  class="rounded-lg border border-slate-700 bg-slate-900 shadow-2xl px-4 py-3
    flex items-center gap-3 max-w-sm pointer-events-auto"
  role="status"
  aria-live="polite"
  data-testid="stub-toast"
  data-action-id={item.actionId}
>
  <span
    class="text-[10px] font-mono uppercase tracking-wider text-amber-400
      bg-amber-500/10 border border-amber-500/30 rounded px-1.5 py-0.5"
  >
    Stub
  </span>
  <span class="text-xs text-slate-200 flex-1">
    {item.reason ?? `Not yet implemented: ${item.actionId}`}
  </span>
  <button
    type="button"
    class="text-slate-500 hover:text-slate-300 text-xs"
    aria-label="Dismiss stub toast"
    onclick={() => stubStore.dismiss(item.id)}
  >
    ✕
  </button>
</div>
