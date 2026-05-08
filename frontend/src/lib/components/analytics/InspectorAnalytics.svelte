<script lang="ts">
  /**
   * Analytics tab — right-pane inspector subsection.
   *
   * Spec anchor: ``BEARINGS_ANALYTICS_v1.md`` §10 (right-pane tab).
   *
   * Three sections top-to-bottom (spec §10.2):
   *
   * * **A — Bucket attribution**: current bucket bars (5h / weekly)
   *   and per-tag attribution table with model-split token counts,
   *   bucket share, and burn rate.
   * * **B — Redundancy**: repeated plug blocks ranked by total token
   *   cost, with tag and last-N scope filters.
   * * **C — Active session plug**: total tokens, status colour, and
   *   per-block breakdown for the currently selected session.
   *
   * Promote actions (spec §7.5): promote buttons appear in Section B
   * (expanded redundancy block detail) and Section C (per-block row).
   * Each flow opens a modal that collects the required fields and calls
   * the backend action endpoint via the injectable test seam.
   *
   * Test seams follow the same pattern as :class:`InspectorUsage`:
   * fetch props default to the live API clients and can be replaced in
   * tests with async fixtures.
   */
  import { onDestroy } from "svelte";
  import {
    ANALYTICS_ATTRIBUTION_WINDOW_5H,
    ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY,
    ANALYTICS_REDUNDANCY_DEFAULT_LAST_N,
    ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS,
    ANALYTICS_REDUNDANCY_LAST_N_MAX,
    ANALYTICS_REDUNDANCY_LAST_N_MIN,
    INSPECTOR_STRINGS,
    PLUG_RED_THRESHOLD_TOKENS,
    PLUG_YELLOW_THRESHOLD_TOKENS,
  } from "../../config";
  import {
    getBucketCurrent,
    getAttribution,
    getRedundancy,
    getSessionPlugSummary,
    promoteToTagMemory,
    promoteToOnOpen,
    type BucketCurrentOut,
    type PromoteToTagMemoryIn,
    type PromoteToOnOpenIn,
    type RedundancyBlockOut,
    type SessionPlugSummaryOut,
    type TagAttributionOut,
  } from "../../api/analytics";
  import { listTags, type TagOut } from "../../api/tags";
  import type { SessionOut } from "../../api/sessions";

  interface Props {
    /**
     * Active session row. Section C reads the plug summary for this
     * session. ``null`` shows the no-session copy; ``undefined`` is
     * the transient loading state.
     */
    session?: SessionOut | null;
    /** Test seams — production callers omit, tests inject fixtures. */
    fetchBucketCurrent?: typeof getBucketCurrent;
    fetchAttribution?: typeof getAttribution;
    fetchRedundancy?: typeof getRedundancy;
    fetchPlugSummary?: typeof getSessionPlugSummary;
    fetchTags?: typeof listTags;
    /** Promote action seams (spec §7.5 Phase 6). */
    doPromoteToTagMemory?: typeof promoteToTagMemory;
    doPromoteToOnOpen?: typeof promoteToOnOpen;
  }

  const {
    session = null,
    fetchBucketCurrent = getBucketCurrent,
    fetchAttribution = getAttribution,
    fetchRedundancy = getRedundancy,
    fetchPlugSummary = getSessionPlugSummary,
    fetchTags = listTags,
    doPromoteToTagMemory = promoteToTagMemory,
    doPromoteToOnOpen = promoteToOnOpen,
  }: Props = $props();

  type LoadState = "idle" | "loading" | "ready" | "error";

  // ----- Section A state -----------------------------------------------
  let bucket: BucketCurrentOut | null = $state(null);
  let attribution: TagAttributionOut[] = $state([]);
  let bucketWindow: string = $state(ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY);
  let bucketLoadState: LoadState = $state("idle");

  // ----- Section B state -----------------------------------------------
  let redundancy: RedundancyBlockOut[] = $state([]);
  let redundancyLoadState: LoadState = $state("idle");
  let filterTag: string | null = $state(null);
  let filterLastN: number = $state(ANALYTICS_REDUNDANCY_DEFAULT_LAST_N);
  let filterMinRepeats: number = $state(ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS);
  let tags: TagOut[] = $state([]);
  let expandedHashes: Set<string> = $state(new Set());

  // ----- Section C state -----------------------------------------------
  let plugSummary: SessionPlugSummaryOut | null = $state(null);
  let plugLoadState: LoadState = $state("idle");

  // ----- Promote modal state (spec §7.5, Phase 6) ----------------------
  // tagMemoryModal: open when user clicks "Promote to tag memory"
  // onOpenModal: open when user clicks "Promote to on_open.sh"
  // promoteHash: hash of the block being promoted
  // promoteStatus: feedback message after a promote attempt
  type PromoteModal = "none" | "tagMemory" | "onOpen";
  let promoteModal: PromoteModal = $state("none");
  let promoteHash: string = $state("");
  let promoteTagInput: string = $state("");
  let promoteMemoryContent: string = $state("");
  let promoteSnippet: string = $state("");
  let promoteWorkingDir: string = $state("");
  let promoteSaving: boolean = $state(false);
  let promoteStatusMsg: string = $state("");

  function openTagMemoryModal(hash: string, content: string): void {
    promoteHash = hash;
    promoteMemoryContent = content;
    promoteTagInput = "";
    promoteStatusMsg = "";
    promoteModal = "tagMemory";
  }

  function openOnOpenModal(hash: string, content: string): void {
    promoteHash = hash;
    promoteSnippet = content;
    promoteWorkingDir = "";
    promoteStatusMsg = "";
    promoteModal = "onOpen";
  }

  function closePromoteModal(): void {
    promoteModal = "none";
    promoteSaving = false;
    promoteStatusMsg = "";
  }

  async function submitTagMemory(): Promise<void> {
    if (!promoteTagInput.trim() || !promoteMemoryContent.trim()) return;
    promoteSaving = true;
    promoteStatusMsg = "";
    try {
      const body: PromoteToTagMemoryIn = {
        tag: promoteTagInput.trim(),
        memory_content: promoteMemoryContent,
        auto_apply_to_next_session: true,
      };
      await doPromoteToTagMemory(promoteHash, body);
      promoteStatusMsg = INSPECTOR_STRINGS.analyticsPromoteTagMemorySuccess;
      promoteSaving = false;
    } catch {
      promoteStatusMsg = INSPECTOR_STRINGS.analyticsPromoteError;
      promoteSaving = false;
    }
  }

  async function submitOnOpen(): Promise<void> {
    if (!promoteSnippet.trim() || !promoteWorkingDir.trim()) return;
    promoteSaving = true;
    promoteStatusMsg = "";
    try {
      const body: PromoteToOnOpenIn = {
        working_directory: promoteWorkingDir.trim(),
        snippet: promoteSnippet,
      };
      await doPromoteToOnOpen(promoteHash, body);
      promoteStatusMsg = INSPECTOR_STRINGS.analyticsPromoteOnOpenSuccess;
      promoteSaving = false;
    } catch {
      promoteStatusMsg = INSPECTOR_STRINGS.analyticsPromoteError;
      promoteSaving = false;
    }
  }

  // Each section has its own abort controller so cancelling a redundancy
  // re-fetch (filter change) doesn't abort the in-flight bucket load.
  let abortSectionA: AbortController | null = null;
  let abortSectionB: AbortController | null = null;
  let abortSectionC: AbortController | null = null;

  // Load section A (bucket + attribution + tags) on mount.
  $effect(() => {
    loadSectionA();
  });

  // Reload section B (redundancy) on mount and whenever filter params change.
  $effect(() => {
    void filterTag;
    void filterLastN;
    void filterMinRepeats;
    loadRedundancy();
  });

  // Reload section C when active session changes.
  $effect(() => {
    const sessionId = session?.id ?? null;
    loadPlugSummary(sessionId);
  });

  onDestroy(() => {
    abortSectionA?.abort();
    abortSectionA = null;
    abortSectionB?.abort();
    abortSectionB = null;
    abortSectionC?.abort();
    abortSectionC = null;
  });

  function loadSectionA(): void {
    abortSectionA?.abort();
    const ctrl = new AbortController();
    abortSectionA = ctrl;
    bucketLoadState = "loading";

    Promise.all([
      fetchBucketCurrent({ signal: ctrl.signal }),
      fetchAttribution({ window: bucketWindow, signal: ctrl.signal }),
      fetchTags({ signal: ctrl.signal }),
    ])
      .then(([bucketData, attrData, tagData]) => {
        if (ctrl.signal.aborted) return;
        bucket = bucketData;
        attribution = [...attrData];
        tags = [...tagData];
        bucketLoadState = "ready";
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        void err;
        bucketLoadState = "error";
      });
  }

  function loadRedundancy(): void {
    abortSectionB?.abort();
    const ctrl = new AbortController();
    abortSectionB = ctrl;
    redundancyLoadState = "loading";

    fetchRedundancy({
      tag: filterTag,
      lastN: filterLastN,
      minRepeats: filterMinRepeats,
      signal: ctrl.signal,
    })
      .then((rows) => {
        if (ctrl.signal.aborted) return;
        redundancy = [...rows];
        redundancyLoadState = "ready";
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        void err;
        redundancyLoadState = "error";
      });
  }

  function loadPlugSummary(sessionId: string | null): void {
    abortSectionC?.abort();
    if (sessionId === null) {
      plugSummary = null;
      plugLoadState = "idle";
      return;
    }
    const ctrl = new AbortController();
    abortSectionC = ctrl;
    plugLoadState = "loading";

    fetchPlugSummary(sessionId, { signal: ctrl.signal })
      .then((data) => {
        if (ctrl.signal.aborted) return;
        plugSummary = data;
        plugLoadState = "ready";
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        void err;
        plugSummary = null;
        plugLoadState = "error";
      });
  }

  function toggleWindow(w: string): void {
    if (bucketWindow === w) return;
    bucketWindow = w;
    abortSectionA?.abort();
    const ctrl = new AbortController();
    abortSectionA = ctrl;
    bucketLoadState = "loading";
    fetchAttribution({ window: w, signal: ctrl.signal })
      .then((attrData) => {
        if (ctrl.signal.aborted) return;
        attribution = [...attrData];
        bucketLoadState = "ready";
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        void err;
        bucketLoadState = "error";
      });
  }

  function toggleExpand(hash: string): void {
    const next = new Set(expandedHashes);
    if (next.has(hash)) {
      next.delete(hash);
    } else {
      next.add(hash);
    }
    expandedHashes = next;
  }

  // ----- Derived helpers -----------------------------------------------

  /**
   * Section A bucket window label for the current selection.
   */
  const bucketWindowLabel = $derived(
    bucketWindow === ANALYTICS_ATTRIBUTION_WINDOW_5H
      ? INSPECTOR_STRINGS.analyticsBucket5hLabel
      : INSPECTOR_STRINGS.analyticsBucketWeeklyLabel,
  );

  /**
   * Attribution rows sorted by share descending (server already
   * sends them sorted by tag name; the UI wants share order).
   */
  const attributionSorted = $derived(
    [...attribution].sort((a, b) => b.share_total - a.share_total),
  );

  function formatTokens(n: number): string {
    return n.toLocaleString();
  }

  function formatShare(fraction: number): string {
    return `${(fraction * 100).toFixed(1)}%`;
  }

  function formatBurn(rate: number): string {
    return `${rate.toFixed(1)}/min`;
  }

  function plugStatusClass(status: string): string {
    if (status === "red") return "text-red-400";
    if (status === "yellow") return "text-yellow-400";
    return "text-green-400";
  }

  function blockTypeLabel(t: string): string {
    const map: Record<string, string> = {
      claude_md: "CLAUDE.md",
      tag_memory: "Tag memory",
      system_addition: "System addition",
      mcp_tools: "MCP tools",
      skill_desc: "Skill",
      other: "Other",
    };
    return map[t] ?? t;
  }
</script>

<section class="inspector-analytics flex flex-col gap-4" data-testid="inspector-analytics">
  <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
    {INSPECTOR_STRINGS.analyticsHeading}
  </h3>

  <!-- ── Section A — Bucket attribution ──────────────────────────────── -->
  <section
    class="inspector-analytics__bucket flex flex-col gap-2"
    data-testid="inspector-analytics-bucket"
  >
    <div class="flex items-center justify-between">
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.analyticsBucketHeading}
      </h4>
      <!-- Window toggle -->
      <div
        class="flex flex-row gap-1 text-xs"
        data-testid="inspector-analytics-bucket-toggle"
        role="group"
        aria-label="Attribution window"
      >
        <button
          type="button"
          class="rounded px-2 py-0.5 font-medium"
          class:inspector-analytics__toggle--active={bucketWindow ===
            ANALYTICS_ATTRIBUTION_WINDOW_5H}
          data-testid="inspector-analytics-bucket-toggle-5h"
          onclick={() => toggleWindow(ANALYTICS_ATTRIBUTION_WINDOW_5H)}
        >
          {INSPECTOR_STRINGS.analyticsBucketToggle5h}
        </button>
        <button
          type="button"
          class="rounded px-2 py-0.5 font-medium"
          class:inspector-analytics__toggle--active={bucketWindow ===
            ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY}
          data-testid="inspector-analytics-bucket-toggle-weekly"
          onclick={() => toggleWindow(ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY)}
        >
          {INSPECTOR_STRINGS.analyticsBucketToggleWeekly}
        </button>
      </div>
    </div>

    {#if bucket !== null}
      <!-- Bucket bars -->
      <div class="flex flex-col gap-1" data-testid="inspector-analytics-bucket-bars">
        {#if bucket.five_hour !== null}
          {@const w = bucket.five_hour}
          <div
            class="flex flex-col gap-0.5"
            data-testid="inspector-analytics-bucket-bar-5h"
            data-percent={w.percent}
          >
            <div class="flex justify-between text-xs text-fg-muted">
              <span>{INSPECTOR_STRINGS.analyticsBucket5hLabel}</span>
              <span>{w.percent.toFixed(1)}%</span>
            </div>
            <div class="h-2 rounded bg-surface-2 overflow-hidden">
              <div
                class="h-full rounded inspector-analytics__bar"
                class:inspector-analytics__bar--warn={w.percent >=
                  PLUG_YELLOW_THRESHOLD_TOKENS / 10}
                class:inspector-analytics__bar--crit={w.percent >= 80}
                style={`width: ${Math.min(100, w.percent).toFixed(2)}%`}
              ></div>
            </div>
            <div class="text-xs text-fg-muted">
              {formatTokens(w.used)} / {formatTokens(w.limit)} tokens
            </div>
          </div>
        {/if}
        {#if bucket.weekly !== null}
          {@const w = bucket.weekly}
          <div
            class="flex flex-col gap-0.5"
            data-testid="inspector-analytics-bucket-bar-weekly"
            data-percent={w.percent}
          >
            <div class="flex justify-between text-xs text-fg-muted">
              <span>{INSPECTOR_STRINGS.analyticsBucketWeeklyLabel}</span>
              <span>{w.percent.toFixed(1)}%</span>
            </div>
            <div class="h-2 rounded bg-surface-2 overflow-hidden">
              <div
                class="h-full rounded inspector-analytics__bar"
                class:inspector-analytics__bar--crit={w.percent >= 80}
                style={`width: ${Math.min(100, w.percent).toFixed(2)}%`}
              ></div>
            </div>
            <div class="text-xs text-fg-muted">
              {formatTokens(w.used)} / {formatTokens(w.limit)} tokens
            </div>
          </div>
        {/if}
        {#if bucket.five_hour === null && bucket.weekly === null}
          <p class="text-fg-muted text-xs" data-testid="inspector-analytics-bucket-no-data">
            {INSPECTOR_STRINGS.analyticsBucketNoData}
          </p>
        {/if}
      </div>
    {:else if bucketLoadState === "loading" || bucketLoadState === "idle"}
      <p class="text-fg-muted" data-testid="inspector-analytics-loading">
        {INSPECTOR_STRINGS.analyticsLoading}
      </p>
    {:else if bucketLoadState === "error"}
      <p class="text-fg-muted" data-testid="inspector-analytics-error">
        {INSPECTOR_STRINGS.analyticsError}
      </p>
    {/if}

    <!-- Per-tag attribution table -->
    <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.analyticsAttributionHeading}
    </h4>
    <p class="text-xs text-fg-muted">{bucketWindowLabel}</p>
    {#if bucketLoadState === "ready"}
      {#if attributionSorted.length === 0}
        <p class="text-fg-muted" data-testid="inspector-analytics-attribution-empty">
          {INSPECTOR_STRINGS.analyticsAttributionEmpty}
        </p>
      {:else}
        <table class="w-full text-xs" data-testid="inspector-analytics-attribution-table">
          <thead>
            <tr class="text-left text-fg-muted">
              <th>{INSPECTOR_STRINGS.analyticsAttributionColTag}</th>
              <th class="text-right">{INSPECTOR_STRINGS.analyticsAttributionColTokens}</th>
              <th class="text-right">{INSPECTOR_STRINGS.analyticsAttributionColShare}</th>
              <th class="text-right">{INSPECTOR_STRINGS.analyticsAttributionColBurnRate}</th>
            </tr>
          </thead>
          <tbody>
            {#each attributionSorted as row (row.tag)}
              <tr
                class="font-mono"
                data-testid="inspector-analytics-attribution-row"
                data-tag={row.tag}
                data-share={row.share_total.toFixed(6)}
              >
                <td class="font-sans">{row.tag}</td>
                <td class="text-right">
                  {#each Object.entries(row.tokens_by_model) as [model, count] (model)}
                    <div
                      data-testid="inspector-analytics-attribution-model-tokens"
                      data-model={model}
                    >
                      {formatTokens(count)}
                    </div>
                  {/each}
                </td>
                <td class="text-right">{formatShare(row.share_total)}</td>
                <td class="text-right">{formatBurn(row.burn_rate_per_min)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}
  </section>

  <!-- ── Section B — Redundancy ───────────────────────────────────────── -->
  <section
    class="inspector-analytics__redundancy flex flex-col gap-2"
    data-testid="inspector-analytics-redundancy"
  >
    <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.analyticsRedundancyHeading}
    </h4>

    <!-- Filter controls -->
    <div
      class="flex flex-row flex-wrap gap-2 text-xs"
      data-testid="inspector-analytics-redundancy-filters"
    >
      <!-- Tag filter -->
      <label class="flex flex-col gap-0.5">
        <span class="text-fg-muted">{INSPECTOR_STRINGS.analyticsRedundancyTagLabel}</span>
        <select
          class="rounded border border-border bg-surface-1 px-1 py-0.5 text-xs"
          data-testid="inspector-analytics-redundancy-tag-select"
          value={filterTag ?? ""}
          onchange={(e) => {
            const v = (e.currentTarget as HTMLSelectElement).value;
            filterTag = v === "" ? null : v;
          }}
        >
          <option value="">{INSPECTOR_STRINGS.analyticsRedundancyTagAll}</option>
          {#each tags as tag (tag.id)}
            <option value={tag.name}>{tag.name}</option>
          {/each}
        </select>
      </label>

      <!-- Last-N slider -->
      <label class="flex flex-col gap-0.5">
        <span class="text-fg-muted"
          >{INSPECTOR_STRINGS.analyticsRedundancyLastNLabel}: {filterLastN}</span
        >
        <input
          type="range"
          min={ANALYTICS_REDUNDANCY_LAST_N_MIN}
          max={ANALYTICS_REDUNDANCY_LAST_N_MAX}
          step="5"
          class="w-24"
          data-testid="inspector-analytics-redundancy-lastn-slider"
          value={filterLastN}
          oninput={(e) => {
            filterLastN = Number((e.currentTarget as HTMLInputElement).value);
          }}
        />
      </label>
    </div>

    <!-- Redundancy list -->
    {#if redundancyLoadState === "loading" || redundancyLoadState === "idle"}
      <p class="text-fg-muted" data-testid="inspector-analytics-redundancy-loading">
        {INSPECTOR_STRINGS.analyticsLoading}
      </p>
    {:else if redundancyLoadState === "error"}
      <p class="text-fg-muted" data-testid="inspector-analytics-redundancy-error">
        {INSPECTOR_STRINGS.analyticsError}
      </p>
    {:else if redundancy.length === 0}
      <p class="text-fg-muted" data-testid="inspector-analytics-redundancy-empty">
        {INSPECTOR_STRINGS.analyticsRedundancyEmpty}
      </p>
    {:else}
      <ul class="flex flex-col gap-1" data-testid="inspector-analytics-redundancy-list">
        {#each redundancy as block (block.hash)}
          <li
            class="rounded border border-border p-2"
            data-testid="inspector-analytics-redundancy-block"
            data-hash={block.hash}
            data-block-type={block.block_type}
            data-repeat-count={block.repeat_count}
            data-total-cost={block.total_cost_tokens}
          >
            <!-- Block header row -->
            <div class="flex items-center justify-between gap-2">
              <div class="flex flex-1 items-center gap-2 min-w-0">
                <span
                  class="shrink-0 rounded bg-surface-2 px-1 py-0.5 text-xs font-medium text-fg-muted"
                  data-testid="inspector-analytics-redundancy-block-type"
                >
                  {blockTypeLabel(block.block_type)}
                </span>
                <span
                  class="truncate font-mono text-xs text-fg"
                  data-testid="inspector-analytics-redundancy-block-preview"
                >
                  {block.sessions[0]
                    ? block.sessions[0].title
                    : (block.source_path ?? block.hash.slice(0, 12))}
                </span>
              </div>
              <div class="flex shrink-0 items-center gap-3 text-xs text-fg-muted">
                <span class="font-mono" data-testid="inspector-analytics-redundancy-block-repeats">
                  ×{block.repeat_count}
                </span>
                <span class="font-mono" data-testid="inspector-analytics-redundancy-block-cost">
                  {formatTokens(block.total_cost_tokens)} tok
                </span>
                <button
                  type="button"
                  class="text-xs text-fg-muted underline"
                  data-testid="inspector-analytics-redundancy-block-expand"
                  onclick={() => toggleExpand(block.hash)}
                  aria-expanded={expandedHashes.has(block.hash)}
                >
                  {expandedHashes.has(block.hash) ? "▲" : "▼"}
                </button>
              </div>
            </div>

            <!-- Expanded detail -->
            {#if expandedHashes.has(block.hash)}
              <div
                class="mt-2 flex flex-col gap-2 text-xs"
                data-testid="inspector-analytics-redundancy-block-detail"
              >
                <div>
                  <span class="text-fg-muted">
                    {block.token_count.toLocaleString()} tok / {block.token_count_model}
                  </span>
                  {#if block.source_path !== null}
                    <span
                      class="ml-2 font-mono text-fg-muted"
                      data-testid="inspector-analytics-redundancy-block-source"
                    >
                      {block.source_path}
                    </span>
                  {/if}
                </div>
                <div>
                  <p class="font-semibold text-fg-muted">
                    {INSPECTOR_STRINGS.analyticsRedundancyExpandSessions}
                  </p>
                  <ul class="mt-1 flex flex-col gap-0.5">
                    {#each block.sessions as ref (ref.id)}
                      <li
                        class="flex items-center gap-2"
                        data-testid="inspector-analytics-redundancy-session-ref"
                        data-session-id={ref.id}
                      >
                        <span class="truncate">{ref.title}</span>
                        {#each ref.tags as t (t)}
                          <span
                            class="shrink-0 rounded bg-surface-2 px-1 text-fg-muted"
                            data-testid="inspector-analytics-redundancy-session-tag"
                          >
                            {t}
                          </span>
                        {/each}
                      </li>
                    {/each}
                  </ul>
                </div>
                <!-- Promote actions (spec §7.5) -->
                <div
                  class="flex flex-row gap-2"
                  data-testid="inspector-analytics-redundancy-promote-actions"
                >
                  <button
                    type="button"
                    class="rounded border border-border px-2 py-0.5 text-xs"
                    data-testid="inspector-analytics-redundancy-promote-tag-memory"
                    onclick={() =>
                      openTagMemoryModal(block.hash, block.source_path ?? block.hash.slice(0, 16))}
                  >
                    {INSPECTOR_STRINGS.analyticsPromoteToTagMemoryBtn}
                  </button>
                  <button
                    type="button"
                    class="rounded border border-border px-2 py-0.5 text-xs"
                    data-testid="inspector-analytics-redundancy-promote-on-open"
                    onclick={() =>
                      openOnOpenModal(block.hash, block.source_path ?? block.hash.slice(0, 16))}
                  >
                    {INSPECTOR_STRINGS.analyticsPromoteToOnOpenBtn}
                  </button>
                </div>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- ── Section C — Active session plug ──────────────────────────────── -->
  <section
    class="inspector-analytics__plug flex flex-col gap-2"
    data-testid="inspector-analytics-plug"
  >
    <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.analyticsPlugHeading}
    </h4>

    {#if session === null || session === undefined}
      <p class="text-fg-muted" data-testid="inspector-analytics-plug-no-session">
        {INSPECTOR_STRINGS.analyticsPlugNoSession}
      </p>
    {:else if plugLoadState === "loading" || plugLoadState === "idle"}
      <p class="text-fg-muted" data-testid="inspector-analytics-plug-loading">
        {INSPECTOR_STRINGS.analyticsLoading}
      </p>
    {:else if plugLoadState === "error" || plugSummary === null}
      <p class="text-fg-muted" data-testid="inspector-analytics-plug-no-data">
        {INSPECTOR_STRINGS.analyticsPlugNoData}
      </p>
    {:else}
      <div
        class="flex items-center gap-2 text-sm"
        data-testid="inspector-analytics-plug-summary"
        data-status={plugSummary.status}
        data-total-tokens={plugSummary.total_tokens}
      >
        <span class="text-fg-muted">{INSPECTOR_STRINGS.analyticsPlugTotalLabel}:</span>
        <span class={`font-mono font-semibold ${plugStatusClass(plugSummary.status)}`}>
          {formatTokens(plugSummary.total_tokens)}
        </span>
        <span
          class={`text-xs ${plugStatusClass(plugSummary.status)}`}
          data-testid="inspector-analytics-plug-status"
        >
          {plugSummary.status}
        </span>
        {#if plugSummary.total_tokens >= PLUG_RED_THRESHOLD_TOKENS}
          <span class="text-xs text-red-400">
            ≥ {PLUG_RED_THRESHOLD_TOKENS.toLocaleString()} tokens — high bucket overhead
          </span>
        {:else if plugSummary.total_tokens >= PLUG_YELLOW_THRESHOLD_TOKENS}
          <span class="text-xs text-yellow-400">
            ≥ {PLUG_YELLOW_THRESHOLD_TOKENS.toLocaleString()} tokens — monitor closely
          </span>
        {/if}
      </div>

      {#if plugSummary.blocks.length === 0}
        <p class="text-fg-muted text-xs" data-testid="inspector-analytics-plug-no-data">
          {INSPECTOR_STRINGS.analyticsPlugNoData}
        </p>
      {:else}
        <table class="w-full text-xs" data-testid="inspector-analytics-plug-table">
          <thead>
            <tr class="text-left text-fg-muted">
              <th>{INSPECTOR_STRINGS.analyticsPlugColType}</th>
              <th class="text-right">{INSPECTOR_STRINGS.analyticsPlugColTokens}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each plugSummary.blocks as blk (blk.hash)}
              <tr
                data-testid="inspector-analytics-plug-block-row"
                data-hash={blk.hash}
                data-block-type={blk.block_type}
              >
                <td>{blockTypeLabel(blk.block_type)}</td>
                <td class="text-right font-mono">{formatTokens(blk.tokens)}</td>
                <td class="text-right">
                  <button
                    type="button"
                    class="text-xs text-fg-muted underline"
                    data-testid="inspector-analytics-plug-block-promote"
                    onclick={() => openTagMemoryModal(blk.hash, blk.block_type)}
                  >
                    {INSPECTOR_STRINGS.analyticsPromoteBtn}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}
  </section>

  <!-- ── Promote modals (spec §7.5) ───────────────────────────────────── -->
  {#if promoteModal !== "none"}
    <!-- Backdrop -->
    <div
      class="fixed inset-0 z-40 bg-black/50"
      data-testid="inspector-analytics-promote-backdrop"
      role="presentation"
      onclick={closePromoteModal}
    ></div>

    <!-- Tag memory modal -->
    {#if promoteModal === "tagMemory"}
      <div
        class="fixed inset-x-4 top-1/4 z-50 mx-auto max-w-md rounded-lg border border-border bg-surface-1 p-4 shadow-xl"
        data-testid="inspector-analytics-promote-tag-memory-modal"
        role="dialog"
        aria-modal="true"
        aria-label={INSPECTOR_STRINGS.analyticsPromoteTagMemoryModalTitle}
      >
        <h3 class="mb-3 text-sm font-semibold">
          {INSPECTOR_STRINGS.analyticsPromoteTagMemoryModalTitle}
        </h3>
        <div class="flex flex-col gap-3">
          <label class="flex flex-col gap-1 text-xs">
            <span class="text-fg-muted">{INSPECTOR_STRINGS.analyticsPromoteTagLabel}</span>
            <input
              type="text"
              class="rounded border border-border bg-surface-2 px-2 py-1 text-xs"
              placeholder={INSPECTOR_STRINGS.analyticsPromoteTagPlaceholder}
              data-testid="inspector-analytics-promote-tag-input"
              bind:value={promoteTagInput}
            />
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="text-fg-muted">{INSPECTOR_STRINGS.analyticsPromoteMemoryContentLabel}</span
            >
            <textarea
              class="h-24 rounded border border-border bg-surface-2 px-2 py-1 font-mono text-xs"
              data-testid="inspector-analytics-promote-memory-content"
              bind:value={promoteMemoryContent}
            ></textarea>
          </label>
          {#if promoteStatusMsg}
            <p class="text-xs" data-testid="inspector-analytics-promote-status">
              {promoteStatusMsg}
            </p>
          {/if}
          <div class="flex justify-end gap-2">
            <button
              type="button"
              class="rounded border border-border px-3 py-1 text-xs"
              data-testid="inspector-analytics-promote-cancel"
              onclick={closePromoteModal}
            >
              {INSPECTOR_STRINGS.analyticsPromoteCancelBtn}
            </button>
            <button
              type="button"
              class="rounded bg-accent px-3 py-1 text-xs font-medium text-white"
              data-testid="inspector-analytics-promote-save"
              disabled={promoteSaving}
              onclick={() => void submitTagMemory()}
            >
              {promoteSaving
                ? INSPECTOR_STRINGS.analyticsPromoteSavingBtn
                : INSPECTOR_STRINGS.analyticsPromoteSaveBtn}
            </button>
          </div>
        </div>
      </div>
    {/if}

    <!-- on_open.sh modal -->
    {#if promoteModal === "onOpen"}
      <div
        class="fixed inset-x-4 top-1/4 z-50 mx-auto max-w-md rounded-lg border border-border bg-surface-1 p-4 shadow-xl"
        data-testid="inspector-analytics-promote-on-open-modal"
        role="dialog"
        aria-modal="true"
        aria-label={INSPECTOR_STRINGS.analyticsPromoteOnOpenModalTitle}
      >
        <h3 class="mb-3 text-sm font-semibold">
          {INSPECTOR_STRINGS.analyticsPromoteOnOpenModalTitle}
        </h3>
        <div class="flex flex-col gap-3">
          <label class="flex flex-col gap-1 text-xs">
            <span class="text-fg-muted">{INSPECTOR_STRINGS.analyticsPromoteWorkingDirLabel}</span>
            <input
              type="text"
              class="rounded border border-border bg-surface-2 px-2 py-1 font-mono text-xs"
              placeholder={INSPECTOR_STRINGS.analyticsPromoteWorkingDirPlaceholder}
              data-testid="inspector-analytics-promote-workdir-input"
              bind:value={promoteWorkingDir}
            />
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="text-fg-muted">{INSPECTOR_STRINGS.analyticsPromoteSnippetLabel}</span>
            <textarea
              class="h-24 rounded border border-border bg-surface-2 px-2 py-1 font-mono text-xs"
              data-testid="inspector-analytics-promote-snippet"
              bind:value={promoteSnippet}
            ></textarea>
          </label>
          {#if promoteStatusMsg}
            <p class="text-xs" data-testid="inspector-analytics-promote-status">
              {promoteStatusMsg}
            </p>
          {/if}
          <div class="flex justify-end gap-2">
            <button
              type="button"
              class="rounded border border-border px-3 py-1 text-xs"
              data-testid="inspector-analytics-promote-cancel"
              onclick={closePromoteModal}
            >
              {INSPECTOR_STRINGS.analyticsPromoteCancelBtn}
            </button>
            <button
              type="button"
              class="rounded bg-accent px-3 py-1 text-xs font-medium text-white"
              data-testid="inspector-analytics-promote-save"
              disabled={promoteSaving}
              onclick={() => void submitOnOpen()}
            >
              {promoteSaving
                ? INSPECTOR_STRINGS.analyticsPromoteSavingBtn
                : INSPECTOR_STRINGS.analyticsPromoteSaveBtn}
            </button>
          </div>
        </div>
      </div>
    {/if}
  {/if}
</section>

<style>
  .inspector-analytics__toggle--active {
    color: rgb(var(--bearings-accent));
    box-shadow: inset 0 -2px 0 rgb(var(--bearings-accent));
  }

  .inspector-analytics__bar {
    background: var(--bearings-accent-info, #38bdf8);
    transition: width 0.2s ease;
  }

  .inspector-analytics__bar--warn {
    background: var(--bearings-accent-warn, #facc15);
  }

  .inspector-analytics__bar--crit {
    background: var(--bearings-accent-error, #ef4444);
  }
</style>
