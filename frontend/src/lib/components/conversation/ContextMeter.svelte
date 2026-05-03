<script lang="ts">
  /**
   * Context/token meter header strip (item 2.2).
   *
   * Reads ``conversationStore.contextUsage`` and
   * ``conversationStore.cacheHitRatio`` — both populated by reducer
   * arms in ``conversation.svelte.ts``. Hidden when no
   * ``context_usage`` frame has arrived in the current session.
   *
   * Layout (left → right):
   *   ┌─────────────────────────────────────────────┐
   *   │ [progress bar]  42%  │  3.2k tokens  │  87% cache  │
   *   └─────────────────────────────────────────────┘
   *
   * Warn band: amber tint on the bar + badge when ``percentage`` is
   * within ``CONTEXT_METER_WARN_BAND_PCT`` of the auto-compact
   * threshold percentage. Falls back to warning above
   * ``(100 - CONTEXT_METER_WARN_BAND_PCT)``% when no threshold is set
   * but auto-compact is enabled.
   *
   * State source:
   *   - ``conversationStore.contextUsage`` — updated by every
   *     ``context_usage`` WS frame.
   *   - ``conversationStore.cacheHitRatio`` — updated by every
   *     ``message_complete`` WS frame.
   */
  import { CONTEXT_METER_STRINGS, CONTEXT_METER_WARN_BAND_PCT } from "../../config";
  import { conversationStore } from "../../stores/conversation.svelte";

  const usage = $derived(conversationStore.contextUsage);
  const cacheHitRatio = $derived(conversationStore.cacheHitRatio);

  /**
   * The auto-compact threshold expressed as a percentage of the full
   * context window (``autoCompactThreshold / maxTokens * 100``).
   * ``null`` when the threshold is unavailable.
   */
  const thresholdPct = $derived(
    usage !== null && usage.autoCompactThreshold !== null && usage.maxTokens > 0
      ? (usage.autoCompactThreshold / usage.maxTokens) * 100
      : null,
  );

  /**
   * ``true`` when the session is within ``CONTEXT_METER_WARN_BAND_PCT``
   * percentage-points of the auto-compact trigger:
   *   - If threshold is known: warn when ``percentage > thresholdPct - band``
   *   - If auto-compact is enabled but threshold unknown: warn above
   *     ``100 - band``%
   *   - Otherwise: no warn band.
   */
  const nearThreshold = $derived(
    usage !== null &&
      (thresholdPct !== null
        ? usage.percentage > thresholdPct - CONTEXT_METER_WARN_BAND_PCT
        : usage.isAutoCompactEnabled === true &&
          usage.percentage > 100 - CONTEXT_METER_WARN_BAND_PCT),
  );

  /** Format a raw token count to a human-readable short string. */
  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  }

  /** Format a ratio 0–1 as a percentage string. */
  function fmtPct(ratio: number): string {
    return `${Math.round(ratio * 100)}%`;
  }
</script>

{#if usage !== null}
  <div
    class="context-meter flex items-center gap-3 border-t border-border px-3 py-1 text-xs"
    class:context-meter--warn={nearThreshold}
    data-testid="context-meter"
    aria-label={CONTEXT_METER_STRINGS.ariaLabel}
  >
    <!-- Progress bar + percentage -->
    <div class="flex flex-1 items-center gap-2">
      <div
        class="relative h-1.5 min-w-[4rem] flex-1 overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-valuenow={Math.round(usage.percentage)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={CONTEXT_METER_STRINGS.ariaLabel}
      >
        <div
          class="h-full rounded-full transition-all duration-300"
          class:bg-accent={!nearThreshold}
          class:bg-amber-400={nearThreshold}
          style="width: {Math.min(usage.percentage, 100)}%"
        ></div>
        <!-- Threshold marker line -->
        {#if thresholdPct !== null}
          <div
            class="absolute inset-y-0 w-px bg-amber-400 opacity-70"
            style="left: {Math.min(thresholdPct, 100)}%"
            aria-hidden="true"
          ></div>
        {/if}
      </div>
      <span
        class="tabular-nums"
        class:text-fg-muted={!nearThreshold}
        class:text-amber-400={nearThreshold}
      >
        {Math.round(usage.percentage)}{CONTEXT_METER_STRINGS.pctSuffix}
      </span>
    </div>

    <!-- Warn badge -->
    {#if nearThreshold}
      <span
        class="rounded bg-amber-400/15 px-1.5 py-0.5 font-medium text-amber-400"
        aria-label={CONTEXT_METER_STRINGS.warnAriaLabel}
        data-testid="context-meter-warn"
      >
        ⚠ compact
      </span>
    {/if}

    <!-- Total tokens -->
    <span class="tabular-nums text-fg-muted" data-testid="context-meter-tokens">
      {fmtTokens(usage.totalTokens)}&nbsp;{CONTEXT_METER_STRINGS.tokensLabel}
    </span>

    <!-- Cache-hit ratio -->
    {#if cacheHitRatio !== null}
      <span class="tabular-nums text-fg-muted" data-testid="context-meter-cache">
        {fmtPct(cacheHitRatio)}&nbsp;{CONTEXT_METER_STRINGS.cacheLabel}
      </span>
    {/if}
  </div>
{/if}

<style>
  .context-meter--warn {
    background-color: rgb(251 191 36 / 0.06);
  }
</style>
