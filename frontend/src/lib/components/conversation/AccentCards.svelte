<script lang="ts">
  /**
   * AccentCards — two value-add info strips above the message list
   * (gap-cycle-01-019).
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"AccentCards".
   *
   * Card 1 (token caching): surfaces the cumulative prompt-cache
   * savings for this session — "Saved X% tokens — N vs M cached".
   * Hidden until ``sessionCacheReadTokens > 0`` so sessions with no
   * cache activity don't show a misleading zero.
   *
   *   savings_pct = cache_read * 0.9 / (executor_input + cache_read)
   *   N (actual cost)    = executor_input + cache_read * 0.1
   *   M (without cache)  = executor_input + cache_read
   *
   * Card 2 (recovery): always rendered. Shows the per-session WS
   * reconnect ring buffer cap — "Recovery armed — Up to 5000 events
   * buffered". Communicates the reconnect guarantee without requiring
   * the user to consult documentation.
   *
   * State source: ``conversationStore.sessionCacheReadTokens`` and
   * ``conversationStore.sessionInputTokens`` (both accumulated from
   * ``message_complete`` frames via ``applySessionTokens``).
   */
  import { ACCENT_CARDS_STRINGS, WS_RING_BUFFER_CAP } from "../../config";
  import { conversationStore } from "../../stores/conversation.svelte";

  const cacheRead = $derived(conversationStore.sessionCacheReadTokens);
  const inputTokens = $derived(conversationStore.sessionInputTokens);

  /**
   * Total tokens the session would have consumed without prompt caching.
   * Used as the denominator for the savings percentage and the "M" in
   * the "N vs M cached" display.
   */
  const totalWithout = $derived(inputTokens + cacheRead);

  /**
   * Percentage of token cost saved via prompt caching.
   * ``Math.round(cache_read * 0.9 / (executor_input + cache_read) * 100)``.
   * ``0`` when ``totalWithout`` is zero (no turns yet).
   */
  const savingsPct = $derived(
    totalWithout > 0 ? Math.round((cacheRead * 0.9 * 100) / totalWithout) : 0,
  );

  /**
   * Actual token cost after the 90 % prompt-cache discount.
   * ``executor_input + cache_read * 0.1`` rounded to the nearest integer.
   * This is "N" in "N vs M cached".
   */
  const actualCost = $derived(Math.round(inputTokens + cacheRead * 0.1));

  /** Format a token count to a compact human-readable string. */
  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  }
</script>

<div
  class="accent-cards flex flex-wrap gap-2 border-b border-border px-3 py-1.5 text-xs"
  data-testid="accent-cards"
  aria-label={ACCENT_CARDS_STRINGS.ariaLabel}
>
  <!-- Card 1: token cache savings (suppressed until cache_read > 0) -->
  {#if cacheRead > 0}
    <div
      class="flex items-center gap-1 rounded bg-accent/10 px-2 py-0.5 text-accent"
      data-testid="accent-card-cache"
    >
      <span data-testid="accent-card-cache-pct">
        {ACCENT_CARDS_STRINGS.cacheSavedLabel}
        {savingsPct}{ACCENT_CARDS_STRINGS.cachePctSuffix}
        {ACCENT_CARDS_STRINGS.cacheSavingsLabel}
      </span>
      <span class="opacity-40" aria-hidden="true">—</span>
      <span data-testid="accent-card-cache-ratio" class="text-accent/70">
        {fmtTokens(actualCost)}
        {ACCENT_CARDS_STRINGS.cacheVsLabel}
        {fmtTokens(totalWithout)}
        {ACCENT_CARDS_STRINGS.cacheSuffix}
      </span>
    </div>
  {/if}

  <!-- Card 2: WS recovery status (always rendered) -->
  <div
    class="flex items-center gap-1 rounded bg-surface-2 px-2 py-0.5 text-fg-muted"
    data-testid="accent-card-recovery"
  >
    <span data-testid="accent-card-recovery-label">
      {ACCENT_CARDS_STRINGS.recoveryArmedLabel}
      —
      {ACCENT_CARDS_STRINGS.recoveryBufferPrefix}
      {WS_RING_BUFFER_CAP}
      {ACCENT_CARDS_STRINGS.recoveryBufferSuffix}
    </span>
  </div>
</div>
