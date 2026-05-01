<script lang="ts">
  /**
   * Bulk title-suggest modal for the master checklist view.
   *
   * Plan: ~/.claude/plans/bulk-retitling-checklist.md.
   *
   * On `open=true`, the modal POSTs the bulk suggester endpoint and
   * renders one row per linked-chat item. Each row shows the item
   * label + current chat title + three candidate-title pills (or an
   * inline error message). The operator picks per row by clicking a
   * pill; clicking the selected pill again deselects it and the row
   * becomes "Skip". Apply walks the picks, PATCHes `/sessions/{id}`
   * for each row that wasn't skipped, and reports a summary count
   * before closing.
   *
   * The default selection is the first candidate ("narrow take") —
   * that's the one most likely to win because it's the tightest
   * abstraction. The operator can flip to medium or wide per row,
   * or skip altogether.
   *
   * Concurrency: serial backend (the route loops; UI shows a single
   * spinner). Apply step is also serial — the title-PATCH calls are
   * cheap, but a parallel dispatch would multiply transient errors;
   * one sequential pass keeps reporting honest.
   */
  import * as api from '$lib/api';
  import type { BulkTitleSuggestItem } from '$lib/api/checklists';

  interface Props {
    /** Two-way bound: parent flips it true to open, modal sets it
     * false on close (Cancel / Apply / outside-click). */
    open: boolean;
    /** Checklist session id — we POST to its bulk-suggest endpoint
     * and the linked chats' titles are what we PATCH on Apply. */
    sessionId: string;
    /** Optional callback after a successful Apply — the parent uses
     * this to refresh its own listing if any displayed titles changed. */
    onApplied?: (summary: ApplySummary) => void;
  }

  export type ApplySummary = {
    applied: number;
    skipped: number;
    errored: number;
  };

  let { open = $bindable(), sessionId, onApplied }: Props = $props();

  /** Local state for the modal lifecycle. `loading` covers the
   * initial bulk-suggest fetch; `applying` covers the per-row
   * PATCH walk on Apply. They're mutually exclusive in the UI. */
  let loading = $state(false);
  let applying = $state(false);
  let fetchError = $state<string | null>(null);
  let rows = $state<BulkTitleSuggestItem[]>([]);
  /** Per-row pick: index into `candidates` for the chosen title, or
   * `null` to skip this row. Defaults to 0 (narrow take) on rows
   * that came back with candidates. Errored rows are not selectable
   * — their entry stays absent from this map. */
  let picks = $state<Record<number, number | null>>({});
  /** Apply summary surfaced inline after a successful Apply pass.
   * Lives until the modal closes. */
  let lastSummary = $state<ApplySummary | null>(null);

  $effect(() => {
    if (!open) {
      // Reset on close so a re-open starts from scratch — stale rows
      // from a prior session shouldn't bleed across opens.
      rows = [];
      picks = {};
      fetchError = null;
      lastSummary = null;
      return;
    }
    void loadSuggestions();
  });

  async function loadSuggestions(): Promise<void> {
    loading = true;
    fetchError = null;
    rows = [];
    picks = {};
    try {
      const result = await api.bulkSuggestItemTitles(sessionId);
      rows = result.items;
      // Default each successful row to candidate 0 (narrow take) so a
      // single Apply click on a fresh batch picks reasonable titles.
      const initial: Record<number, number | null> = {};
      for (const r of rows) {
        if (r.candidates && r.candidates.length > 0) {
          initial[r.item_id] = 0;
        }
      }
      picks = initial;
    } catch (err) {
      fetchError = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  function selectCandidate(itemId: number, idx: number): void {
    const current = picks[itemId];
    // Re-click the selected pill -> skip this row. Otherwise -> select.
    picks = { ...picks, [itemId]: current === idx ? null : idx };
  }

  function isSelected(itemId: number, idx: number): boolean {
    return picks[itemId] === idx;
  }

  /** Count of rows where the operator has a non-null pick. Drives
   * the Apply button enable + summary preview. */
  let pendingCount = $derived(rows.filter((r) => r.candidates && picks[r.item_id] != null).length);

  async function applyPicks(): Promise<void> {
    applying = true;
    const summary: ApplySummary = { applied: 0, skipped: 0, errored: 0 };
    try {
      for (const row of rows) {
        if (!row.candidates) {
          summary.errored += 1;
          continue;
        }
        const idx = picks[row.item_id];
        if (idx == null) {
          summary.skipped += 1;
          continue;
        }
        const title = row.candidates[idx];
        try {
          await api.updateSession(row.chat_session_id, { title });
          summary.applied += 1;
        } catch {
          // Per-row PATCH failure: count as errored but keep going.
          // The summary surfaces the count; the operator can re-run
          // the modal on the failures alone.
          summary.errored += 1;
        }
      }
      lastSummary = summary;
      onApplied?.(summary);
    } finally {
      applying = false;
    }
  }

  function close(): void {
    if (applying || loading) return;
    open = false;
  }
</script>

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    role="dialog"
    aria-modal="true"
    aria-label="Bulk suggest titles"
    data-testid="bulk-title-suggest-modal"
    tabindex="-1"
    onclick={close}
    onkeydown={(e) => e.key === 'Escape' && close()}
  >
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="flex max-h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-md
        border border-slate-800 bg-slate-950 shadow-xl"
      role="document"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <header
        class="flex shrink-0 items-baseline justify-between border-b border-slate-800 px-5 py-3"
      >
        <div>
          <h2 class="text-sm font-semibold text-slate-200">Suggest titles for linked chats</h2>
          <p class="text-xs text-slate-500">
            Pick one title per row, or click the selected pill to skip.
          </p>
        </div>
        <button
          type="button"
          class="text-lg text-slate-500 hover:text-slate-300 disabled:opacity-30"
          onclick={close}
          disabled={applying || loading}
          aria-label="Close"
        >
          ×
        </button>
      </header>

      <div class="flex-1 overflow-y-auto px-5 py-4 text-sm text-slate-300">
        {#if loading}
          <p class="text-slate-500" data-testid="bulk-suggest-loading">
            Asking the model for candidates… (serial; one call per linked chat)
          </p>
        {:else if fetchError}
          <div
            class="rounded border border-rose-900/40 bg-rose-950/30 px-3 py-2 text-rose-300"
            data-testid="bulk-suggest-error"
          >
            <p class="font-medium">Couldn't fetch suggestions:</p>
            <p class="mt-1 text-xs">{fetchError}</p>
            <button
              type="button"
              class="mt-2 rounded bg-slate-800 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700"
              onclick={() => loadSuggestions()}
            >
              Retry
            </button>
          </div>
        {:else if rows.length === 0}
          <p class="text-slate-500" data-testid="bulk-suggest-empty">
            No items linked to chat sessions in this checklist — nothing to retitle.
          </p>
        {:else}
          <ul class="flex flex-col gap-3" data-testid="bulk-suggest-rows">
            {#each rows as row (row.item_id)}
              <li
                class="rounded border border-slate-800 bg-slate-900 p-3"
                data-testid="bulk-suggest-row-{row.item_id}"
              >
                <div class="mb-2 flex items-baseline justify-between gap-2">
                  <span class="truncate text-xs font-medium text-slate-300">{row.label}</span>
                  <span class="font-mono text-[10px] text-slate-500">
                    chat: {row.current_title ?? '(untitled)'}
                  </span>
                </div>
                {#if row.error}
                  <p class="text-xs text-rose-300" data-testid="bulk-suggest-row-error">
                    Skipped — {row.error}
                  </p>
                {:else if row.candidates}
                  <div class="flex flex-wrap gap-2">
                    {#each row.candidates as candidate, idx (idx)}
                      <button
                        type="button"
                        class="rounded-full border px-3 py-1 text-xs transition-colors
                          {isSelected(row.item_id, idx)
                          ? 'border-accent-brand bg-accent-brand-soft/40 text-accent-brand'
                          : 'border-slate-700 bg-slate-950 text-slate-400 hover:border-slate-500 hover:text-slate-200'}"
                        onclick={() => selectCandidate(row.item_id, idx)}
                        data-testid="bulk-suggest-pill-{row.item_id}-{idx}"
                      >
                        {candidate}
                      </button>
                    {/each}
                    {#if picks[row.item_id] == null}
                      <span class="ml-1 self-center text-[11px] text-slate-500">Skip</span>
                    {/if}
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}

        {#if lastSummary}
          <p
            class="mt-4 rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-400"
            data-testid="bulk-suggest-summary"
          >
            Applied {lastSummary.applied} · skipped {lastSummary.skipped} · errored
            {lastSummary.errored}
          </p>
        {/if}
      </div>

      <footer
        class="flex shrink-0 items-center justify-end gap-2 border-t border-slate-800 px-5 py-3"
      >
        <button
          type="button"
          class="rounded border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-300
            hover:bg-slate-800 disabled:opacity-50"
          onclick={close}
          disabled={applying || loading}
          data-testid="bulk-suggest-close"
        >
          {lastSummary ? 'Done' : 'Cancel'}
        </button>
        <button
          type="button"
          class="rounded bg-accent-brand px-3 py-1 text-xs font-medium text-white
            hover:bg-accent-brand/90 disabled:opacity-50"
          onclick={applyPicks}
          disabled={applying || loading || pendingCount === 0 || lastSummary !== null}
          data-testid="bulk-suggest-apply"
        >
          {applying ? 'Applying…' : `Apply ${pendingCount}`}
        </button>
      </footer>
    </div>
  </div>
{/if}
