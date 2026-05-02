<script lang="ts">
  /**
   * Wave 3 spawn-from-reply confirmation card
   * (`~/.claude/plans/classifying-spawn-reply-wave-3.md`).
   *
   * Rendered after the user clicks `⊕ classify` on a finished assistant
   * reply.  Shows the LLM-classified shape, the one-sentence reason, and
   * a preview of the suggested payload so the operator can confirm before
   * committing to the spawn.
   *
   * Three shapes:
   *   single_chat  → one title + description snippet.
   *   multi_chat   → list of N titles (each will become a chat session).
   *   checklist    → list of N item labels (each will become a
   *                  checklist item in a new checklist session).
   *
   * Props:
   *   result       — SpawnClassifyResult from the /classify endpoint.
   *   loading      — true while /classify is in flight (shows spinner).
   *   onApply      — called when the operator confirms; parent drives the
   *                  spawn flow.
   *   onCancel     — called when the operator dismisses the card.
   */

  import type { SpawnClassifyResult } from '$lib/api/sessions';

  type Props = {
    result: SpawnClassifyResult | null;
    loading: boolean;
    onApply: (result: SpawnClassifyResult) => void;
    onCancel: () => void;
  };

  const { result, loading, onApply, onCancel }: Props = $props();

  const shapeLabel: Record<string, string> = {
    single_chat: 'Single chat',
    multi_chat: 'Multiple chats',
    checklist: 'Checklist',
  };

  const shapeBadgeClass: Record<string, string> = {
    single_chat: 'bg-teal-900/60 text-teal-300 border-teal-700',
    multi_chat: 'bg-blue-900/60 text-blue-300 border-blue-700',
    checklist: 'bg-amber-900/60 text-amber-300 border-amber-700',
  };

  function badgeClass(shape: string): string {
    return shapeBadgeClass[shape] ?? 'bg-slate-800 text-slate-300 border-slate-600';
  }
</script>

<!-- Outer wrapper: subtle dark card that sits just below the reply
     action row in the conversation pane.  Non-modal so the operator
     can still read the reply while deciding. -->
<div
  class="mt-2 rounded border border-slate-700 bg-slate-900/80 p-3 text-sm"
  data-testid="spawn-classified-card"
>
  {#if loading}
    <!-- Spinner while /classify is in flight -->
    <div class="flex items-center gap-2 text-slate-400" data-testid="classify-loading">
      <span
        class="inline-block h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-slate-300"
      ></span>
      <span>Classifying reply…</span>
    </div>
  {:else if result}
    <!-- Shape badge + reason -->
    <div class="mb-2 flex items-center gap-2">
      <span
        class="rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider {badgeClass(
          result.shape
        )}"
        data-testid="shape-badge"
      >
        {shapeLabel[result.shape] ?? result.shape}
      </span>
      <span class="text-[11px] text-slate-400" data-testid="classify-reason">{result.reason}</span>
    </div>

    <!-- Shape-specific preview -->
    {#if result.shape === 'single_chat' && result.suggested_single}
      <div class="mb-2 rounded bg-slate-800/60 px-2 py-1.5" data-testid="preview-single">
        <p class="font-medium text-slate-200">{result.suggested_single.title}</p>
        {#if result.suggested_single.description}
          <p class="mt-0.5 line-clamp-2 text-[11px] text-slate-400">
            {result.suggested_single.description}
          </p>
        {/if}
      </div>
    {:else if result.shape === 'multi_chat' && result.suggested_multi}
      <ul class="mb-2 space-y-1" data-testid="preview-multi">
        {#each result.suggested_multi as item, i (i)}
          <li class="flex items-start gap-1.5 rounded bg-slate-800/60 px-2 py-1">
            <span class="mt-0.5 font-mono text-[10px] text-slate-500">{i + 1}.</span>
            <span class="text-slate-200">{item.title}</span>
          </li>
        {/each}
      </ul>
    {:else if result.shape === 'checklist' && result.suggested_checklist}
      <ul class="mb-2 space-y-1" data-testid="preview-checklist">
        {#each result.suggested_checklist as item, i (i)}
          <li class="flex items-start gap-1.5 rounded bg-slate-800/60 px-2 py-1">
            <span class="mt-0.5 text-[10px] text-slate-500">☐</span>
            <span class="text-slate-200">{item.label}</span>
          </li>
        {/each}
      </ul>
    {/if}

    <!-- Action row -->
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="rounded bg-teal-700 px-3 py-1 text-xs font-semibold text-white hover:bg-teal-600 active:bg-teal-800"
        data-testid="classify-apply"
        onclick={() => onApply(result!)}
      >
        Apply
      </button>
      <button
        type="button"
        class="text-xs text-slate-500 hover:text-slate-300"
        data-testid="classify-cancel"
        onclick={onCancel}
      >
        Cancel
      </button>
    </div>
  {/if}
</div>
