<script lang="ts">
  /**
   * Routing subsection — exposes the active session's routing
   * decision history (spec §10 "Modified: Inspector 'Routing'
   * subsection").
   *
   * Behavior anchors (FULLY GOVERNING per plan §"Standards
   * governance" routing scope):
   *
   * - ``docs/model-routing-v1-spec.md`` §10 lines 467-475 enumerate
   *   the four widgets this subsection renders:
   *   1. Current executor + advisor models, source, and reason.
   *   2. Per-message routing badge timeline (scroll-correlated with
   *      the conversation pane — the badge component is the same
   *      :class:`RoutingBadge` the conversation cluster uses).
   *   3. Total advisor calls + tokens this session.
   *   4. Quota delta this session (executor + advisor tokens against
   *      overall bucket; sonnet executor tokens against Sonnet
   *      bucket per spec §4 bucket scoping).
   *   5. "Why this model?" expandable rendering the rule eval chain
   *      (source + matched_rule_id + reason). The full
   *      ``evaluated_rules`` list is wire-side future work — item
   *      1.9's :class:`MessageOut` exposes ``matched_rule_id`` only.
   * - ``docs/architecture-v1.md`` §1.2 enumerates this component as
   *   ``InspectorRouting.svelte`` under ``components/inspector/``.
   * - ``docs/behavior/chat.md`` §"What the user does NOT see in chat"
   *   cross-references this subsection: "the execution chain that
   *   produced the routing decision — see the Inspector Routing
   *   subsection".
   *
   * Data sources:
   *
   * - ``GET /api/sessions/{id}/messages`` (item 1.9) — every assistant
   *   row carries the per-message routing-decision projection plus the
   *   per-model token totals that drive the timeline + advisor totals
   *   + quota-delta widgets.
   *
   * The fetch path is typed-client only — the conversation store
   * already drives a per-session subscription, but its ``TurnRouting``
   * shape strips the per-model token columns, so re-fetching the
   * messages keeps the inspector self-contained.
   */
  import { onDestroy } from "svelte";

  import {
    INSPECTOR_STRINGS,
    NEW_SESSION_STRINGS,
    ROUTING_SOURCE_QUOTA_DOWNGRADE,
    type RoutingSource,
  } from "../../config";
  import { listMessages, type MessageOut } from "../../api/messages";
  import type { SessionOut } from "../../api/sessions";
  import { formatAbsolute } from "../../utils/datetime";
  import RoutingBadge from "../conversation/RoutingBadge.svelte";

  interface Props {
    session: SessionOut;
    /** Test seam — production callers fall through to the typed client. */
    fetchMessages?: typeof listMessages;
  }

  const { session, fetchMessages = listMessages }: Props = $props();

  type LoadState = "idle" | "loading" | "ready" | "error";

  let messages: MessageOut[] = $state([]);
  let loadState: LoadState = $state("idle");

  let activeAbort: AbortController | null = null;
  let lastLoadedSessionId: string | null = null;

  /**
   * The IDs of expanded "Why this model?" panels. Per-message
   * expand/collapse state keyed by message id so re-fetches don't
   * collapse what the user opened.
   */
  let expandedReasons = $state(new Set<string>());

  /**
   * Track the active session id so a sidebar pivot mid-fetch
   * cancels the in-flight call and re-issues against the new id.
   * The ``$effect`` runs on mount and on every ``session.id``
   * change; the cleanup aborts the prior controller.
   */
  $effect(() => {
    const sessionId = session.id;
    if (sessionId === lastLoadedSessionId && loadState !== "idle") {
      return;
    }
    lastLoadedSessionId = sessionId;
    loadFromApi(sessionId);
  });

  onDestroy(() => {
    if (activeAbort !== null) {
      activeAbort.abort();
      activeAbort = null;
    }
  });

  function loadFromApi(sessionId: string): void {
    if (activeAbort !== null) {
      activeAbort.abort();
    }
    const controller = new AbortController();
    activeAbort = controller;
    loadState = "loading";
    fetchMessages(sessionId, { signal: controller.signal })
      .then((page) => {
        if (controller.signal.aborted) {
          return;
        }
        // Inspector fetches all messages (no limit) so has_more is always
        // false; we only need the items array.
        messages = [...page.items];
        loadState = "ready";
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        // The API client already enriches the failure into ``ApiError``;
        // the inspector renders the documented copy rather than echoing
        // the raw status to keep the surface user-facing.
        loadState = "error";
        // Keep the linter from flagging the unused binding while
        // preserving the catch arm — error details surface in devtools.
        void error;
      });
  }

  /**
   * Rows the timeline + totals read against. Filters out user / system
   * rows and legacy rows lacking a routing_source so the per-message
   * badge timeline is "assistant turns with a routing decision" — the
   * spec §10 "per-message routing badge timeline" surface.
   */
  const routedRows = $derived(
    messages.filter((row) => row.executor_model !== null && row.routing_source !== null),
  );

  /** Most recent routed row — the "Current routing" card source. */
  const currentRow = $derived(routedRows.length > 0 ? routedRows[routedRows.length - 1] : null);

  /**
   * Session-total advisor calls + tokens (spec §10 bullet 3).
   * Skipping ``null`` columns keeps legacy rows from contributing
   * NaN to the sum.
   */
  const totalAdvisorCalls = $derived(
    routedRows.reduce((acc, row) => acc + (row.advisor_calls_count ?? 0), 0),
  );
  const totalAdvisorTokens = $derived(
    routedRows.reduce(
      (acc, row) => acc + (row.advisor_input_tokens ?? 0) + (row.advisor_output_tokens ?? 0),
      0,
    ),
  );
  const totalExecutorTokens = $derived(
    routedRows.reduce(
      (acc, row) => acc + (row.executor_input_tokens ?? 0) + (row.executor_output_tokens ?? 0),
      0,
    ),
  );

  /**
   * Quota delta this session (spec §10 bullet 4).
   *
   * ``overall`` sums every per-model token column — both executor
   * and advisor counts hit the cross-model overall bucket per
   * spec §4 "The two buckets".
   *
   * ``sonnet`` sums executor tokens for rows whose
   * ``executor_model === "sonnet"`` per spec §4 "the Sonnet bucket
   * sits underneath the overall" — the bucket counts only Sonnet
   * usage, and advisor calls hit the overall bucket regardless of
   * advisor model.
   */
  const quotaDeltaOverallTokens = $derived(totalExecutorTokens + totalAdvisorTokens);
  const quotaDeltaSonnetTokens = $derived(
    routedRows
      .filter((row) => row.executor_model === "sonnet")
      .reduce(
        (acc, row) => acc + (row.executor_input_tokens ?? 0) + (row.executor_output_tokens ?? 0),
        0,
      ),
  );

  function executorLabel(model: string): string {
    return (
      NEW_SESSION_STRINGS.executorLabels[
        model as keyof typeof NEW_SESSION_STRINGS.executorLabels
      ] ?? model
    );
  }

  function advisorLabel(model: string | null): string {
    if (model === null) {
      return INSPECTOR_STRINGS.routingCurrentAdvisorNone;
    }
    return (
      NEW_SESSION_STRINGS.advisorLabels[model as keyof typeof NEW_SESSION_STRINGS.advisorLabels] ??
      model
    );
  }

  function effortLabel(level: string | null): string {
    if (level === null) {
      return "—";
    }
    return (
      NEW_SESSION_STRINGS.effortLabels[level as keyof typeof NEW_SESSION_STRINGS.effortLabels] ??
      level
    );
  }

  function sourceLabel(source: string | null): string {
    if (source === null) {
      return "—";
    }
    return INSPECTOR_STRINGS.routingSourceLabels[source as RoutingSource] ?? source;
  }

  function isQuotaDowngrade(source: string | null): boolean {
    return source === ROUTING_SOURCE_QUOTA_DOWNGRADE;
  }

  function toggleReason(messageId: string): void {
    const next = new Set(expandedReasons);
    if (next.has(messageId)) {
      next.delete(messageId);
    } else {
      next.add(messageId);
    }
    expandedReasons = next;
  }

  function badgeRouting(row: MessageOut): {
    executorModel: string;
    advisorModel: string | null;
    advisorCallsCount: number;
    effortLevel: string;
    routingSource: string;
    routingReason: string;
  } {
    return {
      executorModel: row.executor_model ?? "",
      advisorModel: row.advisor_model,
      advisorCallsCount: row.advisor_calls_count ?? 0,
      effortLevel: row.effort_level ?? "",
      routingSource: row.routing_source ?? "",
      routingReason: row.routing_reason ?? "",
    };
  }

  function formatTokens(value: number): string {
    return value.toLocaleString();
  }
</script>

<section class="inspector-routing flex flex-col gap-4" data-testid="inspector-routing">
  <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
    {INSPECTOR_STRINGS.routingHeading}
  </h3>

  {#if loadState === "loading" || loadState === "idle"}
    <p class="text-fg-muted" data-testid="inspector-routing-loading">
      {INSPECTOR_STRINGS.routingLoading}
    </p>
  {:else if loadState === "error"}
    <p class="text-fg-muted" data-testid="inspector-routing-error">
      {INSPECTOR_STRINGS.routingError}
    </p>
  {:else if currentRow === null}
    <p class="text-fg-muted" data-testid="inspector-routing-empty">
      {INSPECTOR_STRINGS.routingEmpty}
    </p>
  {:else}
    <section
      class="inspector-routing__current flex flex-col gap-2"
      data-testid="inspector-routing-current"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.routingCurrentHeading}
      </h4>
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentExecutorLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-current-executor">
          {executorLabel(currentRow.executor_model ?? "")}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentAdvisorLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-current-advisor">
          {advisorLabel(currentRow.advisor_model)}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentEffortLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-current-effort">
          {effortLabel(currentRow.effort_level)}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentSourceLabel}</dt>
        <dd
          class="font-mono text-fg"
          data-testid="inspector-routing-current-source"
          data-routing-source={currentRow.routing_source ?? ""}
          data-quota-downgrade={isQuotaDowngrade(currentRow.routing_source) ? "true" : "false"}
        >
          {sourceLabel(currentRow.routing_source)}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentReasonLabel}</dt>
        <dd class="whitespace-pre-wrap text-fg" data-testid="inspector-routing-current-reason">
          {currentRow.routing_reason ?? ""}
        </dd>
      </dl>
    </section>

    <section
      class="inspector-routing__totals flex flex-col gap-2"
      data-testid="inspector-routing-totals"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.routingTotalsHeading}
      </h4>
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingTotalsAdvisorCallsLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-total-advisor-calls">
          {formatTokens(totalAdvisorCalls)}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingTotalsAdvisorTokensLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-total-advisor-tokens">
          {formatTokens(totalAdvisorTokens)}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingTotalsExecutorTokensLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-total-executor-tokens">
          {formatTokens(totalExecutorTokens)}
        </dd>
      </dl>
    </section>

    <section
      class="inspector-routing__quota-delta flex flex-col gap-2"
      data-testid="inspector-routing-quota-delta"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.routingQuotaDeltaHeading}
      </h4>
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingQuotaDeltaOverallLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-quota-delta-overall">
          {formatTokens(quotaDeltaOverallTokens)}
        </dd>

        <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingQuotaDeltaSonnetLabel}</dt>
        <dd class="font-mono text-fg" data-testid="inspector-routing-quota-delta-sonnet">
          {formatTokens(quotaDeltaSonnetTokens)}
        </dd>
      </dl>
    </section>

    <section
      class="inspector-routing__timeline flex flex-col gap-2"
      data-testid="inspector-routing-timeline"
    >
      <h4 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        {INSPECTOR_STRINGS.routingTimelineHeading}
      </h4>
      {#if routedRows.length === 0}
        <p class="text-fg-muted" data-testid="inspector-routing-timeline-empty">
          {INSPECTOR_STRINGS.routingTimelineEmpty}
        </p>
      {:else}
        <ol class="flex flex-col gap-2" data-testid="inspector-routing-timeline-list">
          {#each routedRows as row (row.id)}
            <li
              class="inspector-routing__timeline-row flex flex-col gap-1 rounded border border-border bg-surface-1 p-2"
              data-testid="inspector-routing-timeline-row"
              data-message-id={row.id}
            >
              <div class="flex flex-row items-center gap-2 text-xs text-fg-muted">
                <RoutingBadge routing={badgeRouting(row)} />
                <span class="font-mono">{formatAbsolute(row.created_at)}</span>
              </div>
              <button
                type="button"
                class="self-start text-xs text-fg-muted underline"
                data-testid="inspector-routing-why-toggle"
                data-message-id={row.id}
                aria-expanded={expandedReasons.has(row.id)}
                onclick={() => toggleReason(row.id)}
              >
                {INSPECTOR_STRINGS.routingTimelineWhyLabel}
              </button>
              {#if expandedReasons.has(row.id)}
                <dl
                  class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 pl-2 text-xs"
                  data-testid="inspector-routing-why-body"
                  data-message-id={row.id}
                >
                  <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentSourceLabel}</dt>
                  <dd class="font-mono text-fg" data-routing-source={row.routing_source ?? ""}>
                    {sourceLabel(row.routing_source)}
                  </dd>

                  <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingTimelineMatchedRuleLabel}</dt>
                  <dd class="font-mono text-fg">
                    {#if row.matched_rule_id !== null}
                      #{row.matched_rule_id}
                    {:else}
                      {INSPECTOR_STRINGS.routingTimelineNoMatchedRule}
                    {/if}
                  </dd>

                  {#if row.evaluated_rules.length > 0}
                    <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingTimelineEvalChainLabel}</dt>
                    <dd
                      class="font-mono text-fg"
                      data-testid="inspector-routing-eval-chain"
                      data-message-id={row.id}
                    >
                      {#each row.evaluated_rules as ruleId, i (ruleId)}
                        {#if i > 0}<span class="text-fg-muted"> → </span>{/if}
                        <span
                          class={ruleId === row.matched_rule_id
                            ? "text-success font-semibold"
                            : "text-fg-muted"}
                          title={ruleId === row.matched_rule_id ? "matched" : "skipped"}
                        >#{ruleId}</span>
                      {/each}
                      {#if row.matched_rule_id === null}
                        <span class="text-fg-muted"> → default</span>
                      {/if}
                    </dd>
                  {/if}

                  <dt class="text-fg-muted">{INSPECTOR_STRINGS.routingCurrentReasonLabel}</dt>
                  <dd class="whitespace-pre-wrap text-fg">
                    {row.routing_reason ?? ""}
                  </dd>
                </dl>
              {/if}
            </li>
          {/each}
        </ol>
      {/if}
    </section>
  {/if}
</section>
