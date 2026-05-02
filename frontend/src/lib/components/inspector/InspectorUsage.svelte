<script lang="ts">
  /**
   * Usage subsection — exposes the rolling-window quota + token
   * rollups (spec §10 "New: Usage tab in the inspector").
   *
   * Behavior anchors (FULLY GOVERNING per plan §"Standards
   * governance" routing scope):
   *
   * - ``docs/model-routing-v1-spec.md`` §10 lines 477-484 enumerate
   *   the four widgets:
   *   1. Headroom remaining chart — rolling 7-day plot of overall +
   *      Sonnet bucket consumption with reset markers (spec §7
   *      "Quota efficiency" + §10).
   *   2. By-model table — per-model token totals this week.
   *   3. Advisor effectiveness widget — calls/sessions, advisor
   *      tokens / total tokens, qualitative read.
   *   4. Rules-to-review list — rules with override rate > 30 %
   *      over the last 14 days (spec §8 + §10).
   * - ``docs/architecture-v1.md`` §1.2 enumerates this component as
   *   ``InspectorUsage.svelte`` under ``components/inspector/``.
   * - ``docs/behavior/chat.md`` §"What the user does NOT see in
   *   chat" cross-references this subsection.
   *
   * Data sources:
   *
   * - ``GET /api/quota/history?days=7`` — headroom-chart series.
   * - ``GET /api/usage/by_model?period=week`` — by-model table +
   *   advisor-effectiveness aggregate.
   * - ``GET /api/usage/override_rates?days=14`` — rules-to-review.
   *
   * The chart is rendered as inline-SVG line plots — no external
   * charting dependency keeps the bundle slim and the rendering
   * deterministic for screenshot review. Per spec §10 "with reset
   * markers" we plot a marker at every snapshot whose
   * ``*_resets_at`` advances past the previous row's value.
   */
  import { onDestroy } from "svelte";

  import {
    INSPECTOR_STRINGS,
    NEW_SESSION_STRINGS,
    OVERRIDE_RATE_REVIEW_THRESHOLD,
    OVERRIDE_RATE_WINDOW_DAYS,
    QUOTA_BAR_RED_PCT,
    QUOTA_BAR_YELLOW_PCT,
    USAGE_HEADROOM_WINDOW_DAYS,
  } from "../../config";
  import { getQuotaHistory, type QuotaSnapshot } from "../../api/quota";
  import {
    getOverrideRates,
    getUsageByModel,
    type OverrideRateOut,
    type UsageByModelRow,
  } from "../../api/usage";
  import type { SessionOut } from "../../api/sessions";

  interface Props {
    /**
     * Active session — accepted to align with the other inspector
     * subsections' contract (the shell passes the same row to every
     * tab). The Usage rollups are app-wide; the prop is unused inside
     * the body but kept on the public surface so the shell doesn't
     * need a tab-specific switch. Optional so the standalone
     * ``/analytics`` page (closing-sweep audit P1.8) can mount this
     * component without synthesising a stub row.
     */
    session?: SessionOut;
    /** Test seams. */
    fetchHistory?: typeof getQuotaHistory;
    fetchByModel?: typeof getUsageByModel;
    fetchOverrideRates?: typeof getOverrideRates;
  }

  // ``session`` is destructured under an underscore alias because the
  // Usage rollups are app-wide — the prop sits on the public surface
  // for shell symmetry (every inspector subsection takes the same
  // ``session`` argument) but the body never reads it. A future
  // per-session pivot would drop the underscore.
  const {
    session: _session,
    fetchHistory = getQuotaHistory,
    fetchByModel = getUsageByModel,
    fetchOverrideRates = getOverrideRates,
  }: Props = $props();

  type LoadState = "idle" | "loading" | "ready" | "error";

  let history: QuotaSnapshot[] = $state([]);
  let byModel: UsageByModelRow[] = $state([]);
  let overrideRates: OverrideRateOut[] = $state([]);
  let loadState: LoadState = $state("idle");

  let activeAbort: AbortController | null = null;

  $effect(() => {
    loadAll();
  });

  onDestroy(() => {
    if (activeAbort !== null) {
      activeAbort.abort();
      activeAbort = null;
    }
  });

  function loadAll(): void {
    if (activeAbort !== null) {
      activeAbort.abort();
    }
    const controller = new AbortController();
    activeAbort = controller;
    loadState = "loading";
    Promise.all([
      fetchHistory({ days: USAGE_HEADROOM_WINDOW_DAYS, signal: controller.signal }),
      fetchByModel({ period: "week", signal: controller.signal }),
      fetchOverrideRates({ days: OVERRIDE_RATE_WINDOW_DAYS, signal: controller.signal }),
    ])
      .then(([historyRows, byModelRows, rateRows]) => {
        if (controller.signal.aborted) {
          return;
        }
        history = [...historyRows];
        byModel = [...byModelRows];
        overrideRates = [...rateRows];
        loadState = "ready";
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        loadState = "error";
        void error;
      });
  }

  // ----- Headroom chart series -----------------------------------------

  /**
   * Inline-SVG geometry. Width is unitless — the SVG scales to its
   * container via the viewBox; the height is fixed so the two line
   * plots have consistent visual weight independent of viewport size.
   */
  const CHART_WIDTH = 600;
  const CHART_HEIGHT = 120;
  const CHART_PADDING_X = 8;
  const CHART_PADDING_Y = 8;

  interface ChartPoint {
    x: number;
    y: number;
    capturedAt: number;
    usedPct: number;
    resetMarker: boolean;
  }

  function buildSeries(
    snapshots: QuotaSnapshot[],
    select: (s: QuotaSnapshot) => number | null,
    selectResetsAt: (s: QuotaSnapshot) => number | null,
  ): ChartPoint[] {
    if (snapshots.length === 0) {
      return [];
    }
    const usable = snapshots.filter((s) => select(s) !== null);
    if (usable.length === 0) {
      return [];
    }
    const minX = usable[0].captured_at;
    const maxX = usable[usable.length - 1].captured_at;
    const xSpan = Math.max(1, maxX - minX);
    const innerW = CHART_WIDTH - CHART_PADDING_X * 2;
    const innerH = CHART_HEIGHT - CHART_PADDING_Y * 2;
    let prevResetsAt: number | null = null;
    return usable.map((snapshot) => {
      const usedPct = select(snapshot) ?? 0;
      const x = CHART_PADDING_X + ((snapshot.captured_at - minX) / xSpan) * innerW;
      const y = CHART_PADDING_Y + usedPct * innerH;
      const resetsAt = selectResetsAt(snapshot);
      const isReset = resetsAt !== null && prevResetsAt !== null && resetsAt > prevResetsAt;
      if (resetsAt !== null) {
        prevResetsAt = resetsAt;
      }
      return {
        x,
        y,
        capturedAt: snapshot.captured_at,
        usedPct,
        resetMarker: isReset,
      };
    });
  }

  function pointsToPath(points: ChartPoint[]): string {
    if (points.length === 0) {
      return "";
    }
    const segments = points.map(
      (p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`,
    );
    return segments.join(" ");
  }

  const overallSeries = $derived(
    buildSeries(
      history,
      (s) => s.overall_used_pct,
      (s) => s.overall_resets_at,
    ),
  );
  const sonnetSeries = $derived(
    buildSeries(
      history,
      (s) => s.sonnet_used_pct,
      (s) => s.sonnet_resets_at,
    ),
  );
  const overallPath = $derived(pointsToPath(overallSeries));
  const sonnetPath = $derived(pointsToPath(sonnetSeries));
  const overallResetMarkers = $derived(overallSeries.filter((p) => p.resetMarker));
  const sonnetResetMarkers = $derived(sonnetSeries.filter((p) => p.resetMarker));

  // ----- Advisor-effectiveness aggregate -------------------------------

  /**
   * Aggregate advisor calls / sessions and the advisor token share
   * (advisor / total) per spec §10 "Advisor effectiveness widget".
   *
   * The "qualitative read" string comes from a tiered classifier:
   * heavy share → "pulling its weight"; modest share but non-zero
   * calls → "marginal"; zero calls / share → "rarely consulted".
   * Thresholds are inline because they are presentation-only — the
   * advisor lift figures in spec §2 (~2.7 SWE-bench points at 11.9%
   * cost) sit far above the 0.05 floor.
   */
  const ADVISOR_HEAVY_SHARE = 0.15;
  const ADVISOR_MIN_SHARE = 0.05;

  interface AdvisorEffectiveness {
    sessions: number;
    advisorCalls: number;
    advisorTokens: number;
    executorTokens: number;
    callsPerSession: number;
    advisorShare: number;
    qualitativeRead: string;
  }

  const advisorEffectiveness = $derived<AdvisorEffectiveness | null>(
    computeAdvisorEffectiveness(byModel),
  );

  function computeAdvisorEffectiveness(rows: UsageByModelRow[]): AdvisorEffectiveness | null {
    if (rows.length === 0) {
      return null;
    }
    let sessions = 0;
    let advisorCalls = 0;
    let advisorTokens = 0;
    let executorTokens = 0;
    for (const row of rows) {
      if (row.role === "executor") {
        executorTokens += row.input_tokens + row.output_tokens;
        sessions = Math.max(sessions, row.sessions);
      } else if (row.role === "advisor") {
        advisorCalls += row.advisor_calls;
        advisorTokens += row.input_tokens + row.output_tokens;
      }
    }
    if (sessions === 0 && advisorCalls === 0 && executorTokens === 0) {
      return null;
    }
    const total = executorTokens + advisorTokens;
    const advisorShare = total > 0 ? advisorTokens / total : 0;
    const callsPerSession = sessions > 0 ? advisorCalls / sessions : 0;
    let qualitativeRead: string;
    if (advisorShare >= ADVISOR_HEAVY_SHARE) {
      qualitativeRead = INSPECTOR_STRINGS.usageAdvisorEffectivenessQualPulling;
    } else if (advisorShare >= ADVISOR_MIN_SHARE) {
      qualitativeRead = INSPECTOR_STRINGS.usageAdvisorEffectivenessQualMarginal;
    } else {
      qualitativeRead = INSPECTOR_STRINGS.usageAdvisorEffectivenessQualUnused;
    }
    return {
      sessions,
      advisorCalls,
      advisorTokens,
      executorTokens,
      callsPerSession,
      advisorShare,
      qualitativeRead,
    };
  }

  // ----- Rules-to-review list ------------------------------------------

  /**
   * Spec §8 / §10 surface rules with ``override_rate > 30 %``. The
   * server marks the threshold via the ``review`` boolean; the UI
   * defends against a future change by checking
   * :data:`OVERRIDE_RATE_REVIEW_THRESHOLD` locally as a belt-and-
   * braces filter.
   */
  const rulesToReview = $derived(
    overrideRates.filter((r) => r.review || r.rate > OVERRIDE_RATE_REVIEW_THRESHOLD),
  );

  // ----- Helpers --------------------------------------------------------

  function modelLabel(model: string): string {
    return (
      NEW_SESSION_STRINGS.executorLabels[
        model as keyof typeof NEW_SESSION_STRINGS.executorLabels
      ] ??
      NEW_SESSION_STRINGS.advisorLabels[model as keyof typeof NEW_SESSION_STRINGS.advisorLabels] ??
      model
    );
  }

  function formatTokens(value: number): string {
    return value.toLocaleString();
  }

  function formatPct(fraction: number): string {
    return `${Math.round(fraction * 100)}%`;
  }

  function formatRate(rate: number): string {
    return `${(rate * 100).toFixed(1)}%`;
  }
</script>

<section class="inspector-usage flex flex-col gap-4" data-testid="inspector-usage">
  <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
    {INSPECTOR_STRINGS.usageHeading}
  </h3>

  {#if loadState === "loading" || loadState === "idle"}
    <p class="text-fg-muted" data-testid="inspector-usage-loading">
      {INSPECTOR_STRINGS.usageLoading}
    </p>
  {:else if loadState === "error"}
    <p class="text-fg-muted" data-testid="inspector-usage-error">
      {INSPECTOR_STRINGS.usageError}
    </p>
  {:else}
    <section
      class="inspector-usage__headroom flex flex-col gap-1"
      data-testid="inspector-usage-headroom"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.usageHeadroomHeading}
      </h4>
      <p class="text-xs text-fg-muted">{INSPECTOR_STRINGS.usageHeadroomCaption}</p>
      {#if overallSeries.length === 0 && sonnetSeries.length === 0}
        <p class="text-fg-muted" data-testid="inspector-usage-headroom-empty">
          {INSPECTOR_STRINGS.usageHeadroomEmpty}
        </p>
      {:else}
        <svg
          class="inspector-usage__chart"
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={INSPECTOR_STRINGS.usageHeadroomCaption}
          data-testid="inspector-usage-headroom-chart"
          data-overall-points={overallSeries.length}
          data-sonnet-points={sonnetSeries.length}
        >
          <line
            x1={CHART_PADDING_X}
            x2={CHART_WIDTH - CHART_PADDING_X}
            y1={CHART_PADDING_Y + (CHART_HEIGHT - CHART_PADDING_Y * 2) * QUOTA_BAR_YELLOW_PCT}
            y2={CHART_PADDING_Y + (CHART_HEIGHT - CHART_PADDING_Y * 2) * QUOTA_BAR_YELLOW_PCT}
            class="inspector-usage__threshold inspector-usage__threshold--yellow"
            data-testid="inspector-usage-headroom-threshold-yellow"
          />
          <line
            x1={CHART_PADDING_X}
            x2={CHART_WIDTH - CHART_PADDING_X}
            y1={CHART_PADDING_Y + (CHART_HEIGHT - CHART_PADDING_Y * 2) * QUOTA_BAR_RED_PCT}
            y2={CHART_PADDING_Y + (CHART_HEIGHT - CHART_PADDING_Y * 2) * QUOTA_BAR_RED_PCT}
            class="inspector-usage__threshold inspector-usage__threshold--red"
            data-testid="inspector-usage-headroom-threshold-red"
          />
          {#if overallPath !== ""}
            <path
              d={overallPath}
              class="inspector-usage__line inspector-usage__line--overall"
              data-testid="inspector-usage-headroom-overall-line"
            />
          {/if}
          {#if sonnetPath !== ""}
            <path
              d={sonnetPath}
              class="inspector-usage__line inspector-usage__line--sonnet"
              data-testid="inspector-usage-headroom-sonnet-line"
            />
          {/if}
          {#each overallResetMarkers as marker (marker.capturedAt)}
            <circle
              cx={marker.x}
              cy={marker.y}
              r="3"
              class="inspector-usage__marker inspector-usage__marker--overall"
              data-testid="inspector-usage-headroom-reset-marker"
              data-bucket="overall"
            />
          {/each}
          {#each sonnetResetMarkers as marker (marker.capturedAt)}
            <circle
              cx={marker.x}
              cy={marker.y}
              r="3"
              class="inspector-usage__marker inspector-usage__marker--sonnet"
              data-testid="inspector-usage-headroom-reset-marker"
              data-bucket="sonnet"
            />
          {/each}
        </svg>
        <ul
          class="flex flex-row gap-3 text-xs text-fg-muted"
          data-testid="inspector-usage-headroom-legend"
        >
          <li class="inspector-usage__legend-item">
            <span class="inspector-usage__swatch inspector-usage__swatch--overall"></span>
            {INSPECTOR_STRINGS.usageHeadroomOverallLabel}
          </li>
          <li class="inspector-usage__legend-item">
            <span class="inspector-usage__swatch inspector-usage__swatch--sonnet"></span>
            {INSPECTOR_STRINGS.usageHeadroomSonnetLabel}
          </li>
        </ul>
      {/if}
    </section>

    <section
      class="inspector-usage__by-model flex flex-col gap-1"
      data-testid="inspector-usage-by-model"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.usageByModelHeading}
      </h4>
      {#if byModel.length === 0}
        <p class="text-fg-muted" data-testid="inspector-usage-by-model-empty">
          {INSPECTOR_STRINGS.usageByModelEmpty}
        </p>
      {:else}
        <table class="w-full text-xs" data-testid="inspector-usage-by-model-table">
          <thead>
            <tr class="text-left text-fg-muted">
              <th>{INSPECTOR_STRINGS.usageByModelColModel}</th>
              <th>{INSPECTOR_STRINGS.usageByModelColRole}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageByModelColInputTokens}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageByModelColOutputTokens}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageByModelColAdvisorCalls}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageByModelColCacheReadTokens}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageByModelColSessions}</th>
            </tr>
          </thead>
          <tbody>
            {#each byModel as row (`${row.model}::${row.role}`)}
              <tr
                class="font-mono"
                data-testid="inspector-usage-by-model-row"
                data-model={row.model}
                data-role={row.role}
              >
                <td>{modelLabel(row.model)}</td>
                <td>{row.role}</td>
                <td class="text-right">{formatTokens(row.input_tokens)}</td>
                <td class="text-right">{formatTokens(row.output_tokens)}</td>
                <td class="text-right">{formatTokens(row.advisor_calls)}</td>
                <td class="text-right">{formatTokens(row.cache_read_tokens)}</td>
                <td class="text-right">{formatTokens(row.sessions)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section
      class="inspector-usage__advisor-effectiveness flex flex-col gap-1"
      data-testid="inspector-usage-advisor-effectiveness"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.usageAdvisorEffectivenessHeading}
      </h4>
      {#if advisorEffectiveness === null}
        <p class="text-fg-muted" data-testid="inspector-usage-advisor-effectiveness-empty">
          {INSPECTOR_STRINGS.usageAdvisorEffectivenessEmpty}
        </p>
      {:else}
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt class="text-fg-muted">
            {INSPECTOR_STRINGS.usageAdvisorEffectivenessCallsPerSessionLabel}
          </dt>
          <dd
            class="font-mono text-fg"
            data-testid="inspector-usage-advisor-effectiveness-calls-per-session"
          >
            {advisorEffectiveness.callsPerSession.toFixed(2)}
          </dd>

          <dt class="text-fg-muted">
            {INSPECTOR_STRINGS.usageAdvisorEffectivenessShareLabel}
          </dt>
          <dd class="font-mono text-fg" data-testid="inspector-usage-advisor-effectiveness-share">
            {formatPct(advisorEffectiveness.advisorShare)}
          </dd>

          <dt class="text-fg-muted">
            {INSPECTOR_STRINGS.usageAdvisorEffectivenessQualReadLabel}
          </dt>
          <dd class="text-fg" data-testid="inspector-usage-advisor-effectiveness-read">
            {advisorEffectiveness.qualitativeRead}
          </dd>
        </dl>
      {/if}
    </section>

    <section
      class="inspector-usage__rules-to-review flex flex-col gap-1"
      data-testid="inspector-usage-rules-to-review"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.usageRulesToReviewHeading}
      </h4>
      <p class="text-xs text-fg-muted">{INSPECTOR_STRINGS.usageRulesToReviewCaption}</p>
      {#if rulesToReview.length === 0}
        <p class="text-fg-muted" data-testid="inspector-usage-rules-to-review-empty">
          {INSPECTOR_STRINGS.usageRulesToReviewEmpty}
        </p>
      {:else}
        <table class="w-full text-xs" data-testid="inspector-usage-rules-to-review-table">
          <thead>
            <tr class="text-left text-fg-muted">
              <th>{INSPECTOR_STRINGS.usageRulesToReviewColKind}</th>
              <th>{INSPECTOR_STRINGS.usageRulesToReviewColRuleId}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageRulesToReviewColRate}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageRulesToReviewColFired}</th>
              <th class="text-right">{INSPECTOR_STRINGS.usageRulesToReviewColOverridden}</th>
            </tr>
          </thead>
          <tbody>
            {#each rulesToReview as rule (`${rule.rule_kind}::${rule.rule_id}`)}
              <tr
                class="font-mono inspector-usage__review-row"
                data-testid="inspector-usage-rules-to-review-row"
                data-rule-kind={rule.rule_kind}
                data-rule-id={rule.rule_id}
                data-rate={rule.rate.toFixed(4)}
              >
                <td>{rule.rule_kind}</td>
                <td>#{rule.rule_id}</td>
                <td class="text-right">{formatRate(rule.rate)}</td>
                <td class="text-right">{formatTokens(rule.fired_count)}</td>
                <td class="text-right">{formatTokens(rule.overridden_count)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}
</section>

<style>
  /* Inline-SVG plot — colours come from theme tokens with fallbacks
   * so the chart stays readable even before item 2.9's theme provider
   * lands. The thresholds match the QuotaBars yellow / red rules. */
  .inspector-usage__chart {
    width: 100%;
    height: 8rem;
    background: var(--bearings-surface-1, transparent);
  }
  .inspector-usage__line {
    fill: none;
    stroke-width: 1.5;
  }
  .inspector-usage__line--overall {
    stroke: var(--bearings-accent-info, #38bdf8);
  }
  .inspector-usage__line--sonnet {
    stroke: var(--bearings-accent-ok, #4ade80);
  }
  .inspector-usage__threshold {
    stroke-width: 1;
    stroke-dasharray: 3 3;
  }
  .inspector-usage__threshold--yellow {
    stroke: var(--bearings-accent-warn, #facc15);
  }
  .inspector-usage__threshold--red {
    stroke: var(--bearings-accent-error, #ef4444);
  }
  .inspector-usage__marker {
    stroke: none;
  }
  .inspector-usage__marker--overall {
    fill: var(--bearings-accent-info, #38bdf8);
  }
  .inspector-usage__marker--sonnet {
    fill: var(--bearings-accent-ok, #4ade80);
  }
  .inspector-usage__legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
  }
  .inspector-usage__swatch {
    display: inline-block;
    width: 0.75rem;
    height: 0.25rem;
    border-radius: 9999px;
  }
  .inspector-usage__swatch--overall {
    background: var(--bearings-accent-info, #38bdf8);
  }
  .inspector-usage__swatch--sonnet {
    background: var(--bearings-accent-ok, #4ade80);
  }
  .inspector-usage__review-row {
    background: var(--bearings-surface-2, rgba(250, 204, 21, 0.08));
  }
</style>
