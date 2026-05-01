<script lang="ts">
  /**
   * Analytics page — Phase 6 of the v1.0.0 dashboard redesign. The
   * mockup put a top-level `/analytics` route in the sidebar nav for
   * the per-instance "how have I been using Bearings?" view; this
   * ships the real surface behind the placeholder Phase 2c wired up.
   *
   * Single fetch (`GET /api/analytics/summary?days=30`) drives the
   * whole page — KPI tiles + sessions-by-day bar chart + top tags
   * list. Per-card endpoints would multiply round-trips without
   * changing the freshness story; the page is a periodic snapshot,
   * refreshed on user action, not a live stream.
   *
   * The bar chart is hand-rolled inline divs, no chart library. Each
   * bucket is a vertical bar whose height is `count / max * 100%`,
   * with a hover title carrying the exact day + count. 30 buckets at
   * one bar each fits cleanly in the column width without a scroll;
   * pulling in a dep for one chart isn't worth the bytes.
   *
   * Empty database renders all zeros plus a 30-day flat row of
   * empty bars — honest about a fresh install, no dummy "demo data"
   * fakery.
   */
  import { onMount } from 'svelte';
  import * as api from '$lib/api';
  import { billing } from '$lib/stores/billing.svelte';
  import { formatAbsolute } from '$lib/utils/datetime';

  let summary = $state<api.AnalyticsSummary | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function refresh(): Promise<void> {
    loading = true;
    error = null;
    try {
      summary = await api.fetchAnalyticsSummary(30);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void refresh();
  });

  /** Compact human-friendly count: 12_800 → "12.8k", 2_100_000 → "2.1M". */
  function fmt(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
    return String(n);
  }

  let maxDayCount = $derived(
    summary ? Math.max(1, ...summary.sessions_by_day.map((b) => b.count)) : 1
  );

  let maxTagCount = $derived(
    summary ? Math.max(1, ...summary.top_tags.map((t) => t.session_count)) : 1
  );
</script>

<section class="flex h-full flex-col overflow-hidden" data-testid="analytics-page">
  <header
    class="flex shrink-0 items-baseline justify-between gap-3 border-b border-slate-800
      px-6 py-4"
  >
    <div>
      <h1 class="text-lg font-medium text-slate-200">Analytics</h1>
      <p class="text-xs text-slate-500">
        Per-instance rollup. Headline totals are all-time; the activity chart covers the last 30
        days.
      </p>
    </div>
    <button
      type="button"
      class="rounded bg-slate-800 px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-700
        disabled:opacity-50"
      onclick={refresh}
      disabled={loading}
      data-testid="analytics-refresh"
    >
      {loading ? 'Refreshing…' : 'Refresh'}
    </button>
  </header>

  <div class="flex-1 overflow-y-auto px-6 py-4">
    {#if error}
      <div
        class="rounded-md border border-rose-900/40 bg-rose-950/30 p-3 text-sm text-rose-300"
        data-testid="analytics-error"
      >
        Failed to load analytics: {error}
      </div>
    {:else if !summary}
      <p class="text-sm text-slate-500" data-testid="analytics-loading">Loading…</p>
    {:else}
      <!-- KPI tiles -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="analytics-kpis">
        <div class="rounded-md border border-slate-800 bg-slate-900 p-3">
          <div class="text-[10px] uppercase tracking-wider text-slate-500">Sessions</div>
          <div class="mt-1 font-mono text-2xl text-slate-100">
            {fmt(summary.total_sessions)}
          </div>
          <div class="mt-1 text-[11px] text-slate-500">
            <span class="text-emerald-400">{summary.open_sessions} open</span>
            ·
            {summary.closed_sessions} closed
          </div>
        </div>
        <div class="rounded-md border border-slate-800 bg-slate-900 p-3">
          <div class="text-[10px] uppercase tracking-wider text-slate-500">Messages</div>
          <div class="mt-1 font-mono text-2xl text-slate-100">
            {fmt(summary.total_messages)}
          </div>
          <div class="mt-1 text-[11px] text-slate-500">across all sessions</div>
        </div>
        <div class="rounded-md border border-slate-800 bg-slate-900 p-3">
          <div class="text-[10px] uppercase tracking-wider text-slate-500">Tokens</div>
          <div class="mt-1 font-mono text-2xl text-slate-100">{fmt(summary.total_tokens)}</div>
          <div class="mt-1 text-[11px] text-slate-500">
            in {fmt(summary.total_input_tokens)} ·
            <span class="text-emerald-400">cache {fmt(summary.total_cache_read_tokens)}</span>
          </div>
        </div>
        <div class="rounded-md border border-slate-800 bg-slate-900 p-3">
          <div class="text-[10px] uppercase tracking-wider text-slate-500">Cost</div>
          <div class="mt-1 font-mono text-2xl text-slate-100">
            ${summary.total_cost_usd.toFixed(2)}
          </div>
          <div class="mt-1 text-[11px] text-slate-500">
            {#if billing.showTokens}
              subscription billing — see <a class="text-accent-brand hover:underline" href="/tokens"
                >/tokens</a
              > for per-session
            {:else}
              PAYG total
            {/if}
          </div>
        </div>
      </div>

      <!-- Sessions by day (bar chart) -->
      <div
        class="mt-4 rounded-md border border-slate-800 bg-slate-900 p-3"
        data-testid="analytics-sessions-by-day"
      >
        <header class="mb-2 flex items-baseline justify-between">
          <h2 class="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Sessions per day · last 30 days
          </h2>
          <span class="font-mono text-[11px] text-slate-500">peak {maxDayCount}/day</span>
        </header>
        <div class="flex h-24 items-end gap-[2px]" role="img" aria-label="Sessions per day chart">
          {#each summary.sessions_by_day as bucket (bucket.day)}
            <div
              class="flex-1 rounded-sm bg-emerald-700/50 hover:bg-emerald-500"
              style:height="{(bucket.count / maxDayCount) * 100}%"
              style:min-height={bucket.count > 0 ? '2px' : '1px'}
              title="{bucket.day}: {bucket.count} session{bucket.count === 1 ? '' : 's'}"
              data-testid="bar-{bucket.day}"
            ></div>
          {/each}
        </div>
        <div class="mt-1 flex justify-between font-mono text-[10px] text-slate-600">
          <span>{summary.sessions_by_day[0]?.day ?? ''}</span>
          <span>{summary.sessions_by_day[summary.sessions_by_day.length - 1]?.day ?? ''}</span>
        </div>
      </div>

      <!-- Top tags -->
      <div
        class="mt-4 rounded-md border border-slate-800 bg-slate-900 p-3"
        data-testid="analytics-top-tags"
      >
        <header class="mb-2 flex items-baseline justify-between">
          <h2 class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Top tags</h2>
          <span class="font-mono text-[11px] text-slate-500">
            top {summary.top_tags.length}
          </span>
        </header>
        {#if summary.top_tags.length === 0}
          <p class="text-xs text-slate-500">No tags yet.</p>
        {:else}
          <ul class="flex flex-col gap-1.5">
            {#each summary.top_tags as tag (tag.id)}
              <li class="flex items-center gap-2 text-xs" data-testid="top-tag-{tag.id}">
                <span
                  class="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                  style:background-color={tag.color ?? 'rgb(var(--bearings-slate-600))'}
                  aria-hidden="true"
                ></span>
                <span class="min-w-0 flex-1 truncate font-mono text-slate-300">
                  {tag.name}
                </span>
                <div class="relative h-1.5 w-24 shrink-0 rounded-full bg-slate-800">
                  <div
                    class="absolute left-0 top-0 h-1.5 rounded-full bg-emerald-500"
                    style:width="{(tag.session_count / maxTagCount) * 100}%"
                  ></div>
                </div>
                <span class="w-10 shrink-0 text-right font-mono text-slate-500">
                  {tag.session_count}
                </span>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <!-- Footer: token breakdown + cache savings derivation -->
      <div
        class="mt-4 rounded-md border border-slate-800 bg-slate-900 p-3 text-xs"
        data-testid="analytics-token-breakdown"
      >
        <h2 class="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">
          Token breakdown
        </h2>
        <dl class="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-[11px]">
          <dt class="text-slate-500">Input</dt>
          <dd class="text-right text-slate-300">{fmt(summary.total_input_tokens)}</dd>
          <dt class="text-slate-500">Output</dt>
          <dd class="text-right text-slate-300">{fmt(summary.total_output_tokens)}</dd>
          <dt class="text-slate-500">Cache read</dt>
          <dd class="text-right text-emerald-300">{fmt(summary.total_cache_read_tokens)}</dd>
          <dt class="text-slate-500">Cache write</dt>
          <dd class="text-right text-slate-300">
            {fmt(summary.total_cache_creation_tokens)}
          </dd>
        </dl>
      </div>

      <p class="mt-4 text-center text-[10px] text-slate-600">
        Snapshot at {formatAbsolute(new Date().toISOString())}
      </p>
    {/if}
  </div>
</section>
