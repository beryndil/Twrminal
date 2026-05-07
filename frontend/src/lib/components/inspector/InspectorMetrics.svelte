<script lang="ts">
  /**
   * Metrics subsection — per-session token totals and tool-call
   * counters (gap-cycle-09-005).
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"Inspector pane" §"Metrics" documents
   *   the two cards, data sources, and formatting rules.
   *
   * Two cards:
   *
   * 1. **Token totals** — Input / Output / Cache read / Cache write,
   *    each in its own labelled cell. Formatted with the short-notation
   *    helper (``1.2k``, ``3.4M``). Cache-read uses an emerald accent.
   *    Cache-write renders ``—`` — the v18 backend does not yet emit
   *    ``cache_creation_tokens``; the cell is wired so it lights up
   *    once the backend surface lands.
   *
   * 2. **Tool calls** — Total / Running / Failed / Total elapsed.
   *    Running uses amber; Failed uses rose when > 0, slate at 0.
   *    Total elapsed is summed over finished (``done=true``) calls
   *    only; renders ``—`` when no finished calls exist.
   *
   * Token data comes from :data:`conversationStore`'s accumulated
   * ``session*Tokens`` counters (reset on session-switch, accumulated
   * from ``message_complete`` frames). Tool-call counters derive from
   * :data:`conversationStore.turns` (same reactive source used by
   * :class:`InspectorChanges` and :class:`InspectorFiles`).
   *
   * The ``turns`` / ``inputTokens`` / ``outputTokens`` /
   * ``cacheReadTokens`` / ``cacheWriteTokens`` props are test seams —
   * production callers pass nothing and the component reads from the
   * module-singleton store.
   */
  import { INSPECTOR_STRINGS } from "../../config";
  import {
    conversationStore,
    type MessageTurnView,
  } from "../../stores/conversation.svelte";
  import type { SessionOut } from "../../api/sessions";

  interface Props {
    /**
     * Active session row. Accepted for interface parity with the other
     * inspector subsections; the Metrics tab derives its data from
     * :data:`conversationStore`, not from the session row directly.
     */
    session: SessionOut;
    /**
     * Test seam — inject turns directly so each test owns its fixture
     * data without touching the module-singleton store. Production
     * callers pass nothing; the component reads
     * :data:`conversationStore.turns`.
     */
    turns?: readonly MessageTurnView[];
    /**
     * Test seams for the four token-total cells. Production callers
     * pass nothing; the component reads from
     * :data:`conversationStore.session*Tokens`.
     *
     * ``cacheWriteTokens`` defaults to ``null`` — the v18 backend does
     * not emit ``cache_creation_tokens`` yet, so production is always
     * unavailable. Pass a non-null value in tests to exercise the cell.
     */
    inputTokens?: number;
    outputTokens?: number;
    cacheReadTokens?: number;
    cacheWriteTokens?: number | null;
  }

  const {
    session: _session,
    turns: turnsProp = undefined,
    inputTokens: inputTokensProp = undefined,
    outputTokens: outputTokensProp = undefined,
    cacheReadTokens: cacheReadTokensProp = undefined,
    cacheWriteTokens: cacheWriteTokensProp = undefined,
  }: Props = $props();

  /** Active turns: test-injected list when provided, else the store. */
  const activeTurns = $derived(turnsProp ?? conversationStore.turns);

  // ---- Token totals -------------------------------------------------------

  /**
   * Token count sources with test-seam override support.
   * Production path reads the accumulated session counters from the
   * conversation store (reset on session-switch via
   * :func:`resetConversation`).
   */
  const inputTokens = $derived(inputTokensProp ?? conversationStore.sessionInputTokens);
  const outputTokens = $derived(outputTokensProp ?? conversationStore.sessionOutputTokens);
  const cacheReadTokens = $derived(cacheReadTokensProp ?? conversationStore.sessionCacheReadTokens);
  /**
   * Cache-write tokens: the v18 ``message_complete`` event does not
   * carry ``cache_creation_tokens``. The prop defaults to ``undefined``
   * (production) rather than ``null`` so the discriminant below stays
   * clean.
   *
   * When ``undefined``: the backend has not yet surfaced this counter →
   * render ``—``.
   * When ``null``: test explicitly marks it unavailable → render ``—``.
   * When a number: render the formatted value.
   */
  const cacheWriteTokens = $derived<number | null | undefined>(cacheWriteTokensProp);

  // ---- Tool-call counters -------------------------------------------------

  /**
   * Flat list of all tool calls across every assistant turn.
   * Derived reactively from ``activeTurns`` so it updates live as the
   * WebSocket streams new events.
   */
  const allToolCalls = $derived.by(() => {
    const result: import("../../stores/conversation.svelte").ToolCallView[] = [];
    for (const turn of activeTurns) {
      for (const tc of turn.toolCalls) {
        result.push(tc);
      }
    }
    return result;
  });

  const totalCalls = $derived(allToolCalls.length);
  const runningCalls = $derived(allToolCalls.filter((tc) => !tc.done).length);
  const failedCalls = $derived(allToolCalls.filter((tc) => tc.done && tc.ok === false).length);

  /**
   * Sum of ``durationMs`` over finished calls only (``done=true`` and
   * ``durationMs !== null``). In-flight calls are excluded so the
   * elapsed figure only advances when a call completes, not while it
   * is running.
   */
  const totalElapsedMs = $derived(
    allToolCalls.reduce(
      (sum, tc) => sum + (tc.done && tc.durationMs !== null ? tc.durationMs : 0),
      0,
    ),
  );

  /** ``true`` when at least one finished call has a valid duration. */
  const hasFinishedWithDuration = $derived(
    allToolCalls.some((tc) => tc.done && tc.durationMs !== null),
  );

  // ---- Formatters ---------------------------------------------------------

  /**
   * Short-notation token formatter: ``1234 → "1.2k"``, ``1500000 →
   * "1.5M"``. Matches the pattern used by :component:`TokenMeter`,
   * :component:`ContextMeter`, and :component:`AccentCards`.
   */
  function fmtShort(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  }

  /**
   * Human-readable duration from milliseconds.
   *
   * - ``< 1 000 ms`` → ``"Nms"``
   * - ``< 60 000 ms`` → ``"N.Ns"``
   * - ``≥ 60 000 ms`` → ``"Nm Ns"``
   */
  function formatDuration(ms: number): string {
    if (ms < 1_000) return `${ms}ms`;
    if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`;
    const min = Math.floor(ms / 60_000);
    const sec = Math.round((ms % 60_000) / 1_000);
    return `${min}m ${sec}s`;
  }
</script>

<section class="inspector-metrics flex flex-col gap-4" data-testid="inspector-metrics">
  <!-- Token totals card -->
  <section
    class="inspector-metrics__card flex flex-col gap-2"
    data-testid="inspector-metrics-token-totals"
  >
    <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.metricsTokenTotalsHeading}
    </h3>
    <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsTokenInputLabel}</dt>
        <dd
          class="font-mono tabular-nums text-fg"
          data-testid="inspector-metrics-token-input"
        >
          {fmtShort(inputTokens)}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsTokenOutputLabel}</dt>
        <dd
          class="font-mono tabular-nums text-fg"
          data-testid="inspector-metrics-token-output"
        >
          {fmtShort(outputTokens)}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsTokenCacheReadLabel}</dt>
        <dd
          class="font-mono tabular-nums text-emerald-400"
          data-testid="inspector-metrics-token-cache-read"
        >
          {fmtShort(cacheReadTokens)}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsTokenCacheWriteLabel}</dt>
        <dd
          class="font-mono tabular-nums text-fg"
          data-testid="inspector-metrics-token-cache-write"
        >
          {cacheWriteTokens != null
            ? fmtShort(cacheWriteTokens)
            : INSPECTOR_STRINGS.metricsTokenCacheWriteUnavailable}
        </dd>
      </div>
    </dl>
  </section>

  <!-- Tool calls card -->
  <section
    class="inspector-metrics__card flex flex-col gap-2"
    data-testid="inspector-metrics-tool-calls"
  >
    <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.metricsToolCallsHeading}
    </h3>
    <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsToolCallsTotalLabel}</dt>
        <dd
          class="font-mono tabular-nums text-fg"
          data-testid="inspector-metrics-tool-total"
        >
          {totalCalls}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsToolCallsRunningLabel}</dt>
        <dd
          class="font-mono tabular-nums"
          class:text-amber-400={runningCalls > 0}
          class:text-fg-muted={runningCalls === 0}
          data-testid="inspector-metrics-tool-running"
        >
          {runningCalls}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsToolCallsFailedLabel}</dt>
        <dd
          class="font-mono tabular-nums"
          class:text-rose-400={failedCalls > 0}
          class:text-fg-muted={failedCalls === 0}
          data-testid="inspector-metrics-tool-failed"
        >
          {failedCalls}
        </dd>
      </div>
      <div class="flex flex-col gap-0.5">
        <dt class="text-fg-muted">{INSPECTOR_STRINGS.metricsToolCallsElapsedLabel}</dt>
        <dd
          class="font-mono tabular-nums text-fg"
          data-testid="inspector-metrics-tool-elapsed"
        >
          {hasFinishedWithDuration
            ? formatDuration(totalElapsedMs)
            : INSPECTOR_STRINGS.metricsToolCallsElapsedEmpty}
        </dd>
      </div>
    </dl>
  </section>

  <!-- Cross-session link -->
  <p class="text-xs text-fg-muted" data-testid="inspector-metrics-analytics-link">
    <a href="/analytics" class="text-accent hover:underline">
      {INSPECTOR_STRINGS.metricsAnalyticsLink}
    </a>
  </p>
</section>
