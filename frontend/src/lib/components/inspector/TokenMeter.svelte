<script lang="ts">
  /**
   * Subscription-mode token-usage meter (gap-cycle-01-017).
   *
   * Renders the cumulative input and output executor token totals for
   * the active session, coloured according to the overall quota usage
   * percentage. Shown in the conversation header in place of the dollar
   * figure when ``billing.mode = "subscription"`` (Anthropic Max / Pro
   * plans), because a dollar figure is meaningless on a flat-rate plan.
   *
   * Threshold colours mirror the quota-bar thresholds (spec §10):
   *   - Default (``text-fg-muted``): overall usage < 80 %.
   *   - Yellow (``text-amber-400``): 80 % ≤ usage < 95 %.
   *   - Red   (``text-red-400``):   usage ≥ 95 %.
   *
   * Props:
   *   ``inputTokens``   — cumulative executor input tokens this session.
   *   ``outputTokens``  — cumulative executor output tokens this session.
   *   ``overallUsedPct`` — overall quota fraction (0.0–1.0) from the
   *                         latest ``QuotaSnapshot``; ``null`` when the
   *                         quota poller has not yet reported.
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"When the user opens an
   * existing chat" — conversation header band; spec §10 quota-bar
   * thresholds.
   *
   * Placement: ``inspector/`` per architecture-v1.md §1.2 (alongside
   * :component:`ContextMeter`); imported directly from
   * :component:`ConversationHeader` as a header-band primitive.
   */
  import { QUOTA_BAR_RED_PCT, QUOTA_BAR_YELLOW_PCT, TOKEN_METER_STRINGS } from "../../config";

  interface Props {
    /** Cumulative executor input tokens for the active session. */
    inputTokens: number;
    /** Cumulative executor output tokens for the active session. */
    outputTokens: number;
    /**
     * Overall quota fraction (0.0–1.0) from the latest quota snapshot.
     * Drives threshold colour. ``null`` when quota data is unavailable
     * (poller not configured, or first poll not yet completed) — renders
     * in the default muted colour.
     */
    overallUsedPct: number | null;
  }

  const { inputTokens, outputTokens, overallUsedPct }: Props = $props();

  /**
   * ``true`` when overall usage is in the yellow band:
   * ``QUOTA_BAR_YELLOW_PCT`` ≤ usage < ``QUOTA_BAR_RED_PCT``.
   */
  const isWarn = $derived(
    overallUsedPct !== null &&
      overallUsedPct >= QUOTA_BAR_YELLOW_PCT &&
      overallUsedPct < QUOTA_BAR_RED_PCT,
  );

  /**
   * ``true`` when overall usage is at or above the red threshold:
   * usage ≥ ``QUOTA_BAR_RED_PCT``.
   */
  const isDanger = $derived(overallUsedPct !== null && overallUsedPct >= QUOTA_BAR_RED_PCT);

  /** Format a raw token count to a human-readable short string. */
  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  }
</script>

<span
  class="token-meter tabular-nums text-xs"
  class:text-fg-muted={!isWarn && !isDanger}
  class:text-amber-400={isWarn}
  class:text-red-400={isDanger}
  aria-label={isDanger
    ? TOKEN_METER_STRINGS.dangerAriaLabel
    : isWarn
      ? TOKEN_METER_STRINGS.warnAriaLabel
      : TOKEN_METER_STRINGS.ariaLabel}
  data-testid="token-meter"
>
  <span data-testid="token-meter-input">
    {fmtTokens(inputTokens)}&nbsp;{TOKEN_METER_STRINGS.inputLabel}
  </span>
  <span class="mx-1 opacity-40" aria-hidden="true">/</span>
  <span data-testid="token-meter-output">
    {fmtTokens(outputTokens)}&nbsp;{TOKEN_METER_STRINGS.outputLabel}
  </span>
</span>
