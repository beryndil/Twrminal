<script lang="ts">
  /**
   * Inspector Metrics tab — basic per-session metrics surface.
   *
   * Pre-v1.0.1 this was a placeholder pointing at "Phase 6" (which
   * already shipped). The real Analytics page lives at /analytics
   * for the cross-session view; this tab carries the at-a-glance
   * per-session shape: token totals + tool-call counts + cumulative
   * tool-call elapsed.
   *
   * Token totals are sourced from the same `api.getSessionTokens()`
   * call that ContextTab uses; we re-fetch on session switch and on
   * end-of-stream (mirrors ContextTab's $effect pattern). This keeps
   * the two surfaces consistent — they read the same underlying
   * counter — without trying to share state through a store.
   */
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { formatDuration } from '$lib/utils/datetime';
  import * as api from '$lib/api';

  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
    return String(n);
  }

  let tokenTotals = $state<api.TokenTotals | null>(null);
  let prevStreaming = false;

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      tokenTotals = null;
      return;
    }
    api.getSessionTokens(sid).then(
      (r) => {
        if (sessions.selected?.id === sid) tokenTotals = r;
      },
      () => {}
    );
  });

  $effect(() => {
    const active = conversation.streamingActive;
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      prevStreaming = active;
      return;
    }
    if (prevStreaming && !active) {
      api.getSessionTokens(sid).then(
        (r) => {
          if (sessions.selected?.id === sid) tokenTotals = r;
        },
        () => {}
      );
    }
    prevStreaming = active;
  });

  // ---------- tool-call metrics ----------------------------------------

  let totalCalls = $derived(conversation.toolCalls.length);
  let runningCalls = $derived(conversation.toolCalls.filter((c) => c.ok === null).length);
  let failedCalls = $derived(conversation.toolCalls.filter((c) => c.ok === false).length);

  // Sum of finished-call elapsed (ms). In-flight calls don't have a
  // finish time yet so we exclude them; this matches the Analytics
  // page's "completed turn" accounting.
  let totalElapsedMs = $derived(
    conversation.toolCalls.reduce((acc, c) => {
      if (c.finishedAt === null) return acc;
      return acc + (c.finishedAt - c.startedAt);
    }, 0)
  );
</script>

<div class="flex flex-col gap-3 p-4" data-testid="inspector-tab-metrics-content">
  {#if !sessions.selected}
    <p class="text-sm text-slate-500">Select a session to see metrics.</p>
  {:else}
    <!-- ===== Token totals ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="metrics-token-totals"
    >
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
        Token totals
      </h3>
      {#if tokenTotals}
        <dl class="grid grid-cols-2 gap-2 text-xs">
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Input</dt>
            <dd class="font-mono text-sm text-slate-200">{fmtTokens(tokenTotals.input_tokens)}</dd>
          </div>
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Output</dt>
            <dd class="font-mono text-sm text-slate-200">{fmtTokens(tokenTotals.output_tokens)}</dd>
          </div>
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Cache read</dt>
            <dd class="font-mono text-sm text-emerald-300">
              {fmtTokens(tokenTotals.cache_read_tokens)}
            </dd>
          </div>
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Cache write</dt>
            <dd class="font-mono text-sm text-slate-200">
              {fmtTokens(tokenTotals.cache_creation_tokens)}
            </dd>
          </div>
        </dl>
      {:else}
        <p class="text-xs text-slate-500">No tokens billed yet.</p>
      {/if}
    </section>

    <!-- ===== Tool calls ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="metrics-tool-calls"
    >
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
        Tool calls
      </h3>
      <dl class="grid grid-cols-2 gap-2 text-xs">
        <div class="rounded bg-slate-900 px-2 py-1.5">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Total</dt>
          <dd class="font-mono text-sm text-slate-200">{totalCalls}</dd>
        </div>
        <div class="rounded bg-slate-900 px-2 py-1.5">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Running</dt>
          <dd class="font-mono text-sm text-amber-300">{runningCalls}</dd>
        </div>
        <div class="rounded bg-slate-900 px-2 py-1.5">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Failed</dt>
          <dd
            class="font-mono text-sm"
            class:text-rose-300={failedCalls > 0}
            class:text-slate-200={failedCalls === 0}
          >
            {failedCalls}
          </dd>
        </div>
        <div class="rounded bg-slate-900 px-2 py-1.5">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Total elapsed</dt>
          <dd class="font-mono text-sm text-slate-200">
            {totalCalls > 0 ? formatDuration(totalElapsedMs) : '—'}
          </dd>
        </div>
      </dl>
    </section>

    <p class="text-[11px] text-slate-500">
      Cross-session metrics live on the
      <a class="text-emerald-400 hover:underline" href="/analytics">Analytics page</a>.
    </p>
  {/if}
</div>
