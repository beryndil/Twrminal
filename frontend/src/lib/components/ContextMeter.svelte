<script lang="ts">
  import type { ContextUsageState } from '$lib/stores/conversation.svelte';

  /**
   * Compact context-window pressure indicator shown in the conversation
   * header. Sourced from `ClaudeSDKClient.get_context_usage()` emitted
   * as a `context_usage` WS event after every completed turn and seeded
   * from the session row's cached columns (migration 0013) on first
   * paint.
   *
   * Intent: tell Dave at a glance when a session is approaching
   * auto-compact or hard-cap so he can checkpoint / fork / delegate to
   * a sub-agent *before* the detail loss he hit today. The bands are
   * chosen to give him runway, not surprise him:
   *
   *   < 50%  — slate  (ignore: plenty of room)
   *   50-74% — amber  (start watching; any big research turn will push past)
   *   75-89% — orange (compact imminent; decide now — fork or checkpoint)
   *   ≥ 90%  — red    (compact has almost certainly fired or is about to)
   *
   * Auto-compact-disabled sessions bump one band earlier so the user
   * sees "decide now" territory at 50% instead of 75% — without the
   * compaction safety net, the cliff is closer.
   *
   * On top of the percentage bands, a hard 32K-token threshold forces a
   * flashing red pill. Empirically, Claude's recall degrades sharply
   * once the current window exceeds ~32K tokens regardless of the
   * nominal 200K cap — the percentage can still read 17% while real
   * references are already drifting. The flash surfaces that
   * degradation early enough for Dave to checkpoint / fork before the
   * session becomes unreliable.
   */

  /** Empirical recall-degradation threshold. Claude's usable context
   * gets soft past this mark even when the nominal window is far
   * larger, so we warn independent of the percentage bands. Hardcoded
   * for now; a future slice can lift this into config.toml for
   * per-model tuning. */
  const CONTEXT_DEGRADATION_THRESHOLD_TOKENS = 32_000;

  type Props = {
    /** Null while no context snapshot has been captured for this
     * session yet (new session, or pre-migration-0013 session that
     * hasn't completed a turn since the upgrade). */
    context: ContextUsageState | null;
  };

  let { context }: Props = $props();

  /** One-decimal k/M formatter matching TokenMeter's convention. */
  function formatTokens(n: number): string {
    if (!Number.isFinite(n) || n < 0) return '—';
    if (n === 0) return '0';
    if (n < 1_000) return String(n);
    if (n < 1_000_000) {
      const k = n / 1_000;
      return `${k < 100 ? k.toFixed(1) : Math.round(k)}k`;
    }
    const m = n / 1_000_000;
    return `${m < 100 ? m.toFixed(1) : Math.round(m)}M`;
  }

  /** Resolve the threshold band for a given percentage + auto-compact
   * flag. Returns a Tailwind class set (text + background) for the
   * pill. Shifted one band earlier when auto-compact is off because
   * there's no safety net catching an overflow. */
  function bandClass(pct: number, autoCompact: boolean): string {
    const [yellow, orange, red] = autoCompact ? [50, 75, 90] : [40, 60, 80];
    if (pct >= red) return 'text-red-100 bg-red-900/60';
    if (pct >= orange) return 'text-orange-100 bg-orange-900/60';
    if (pct >= yellow) return 'text-amber-100 bg-amber-900/60';
    return 'text-slate-400 bg-slate-800/60';
  }

  const pill = $derived.by(() => {
    if (!context) return null;
    const degraded = context.totalTokens >= CONTEXT_DEGRADATION_THRESHOLD_TOKENS;
    // When past the 32K threshold, force the red band and layer on the
    // flash animation (motion-safe so reduced-motion users get solid
    // red without the pulse). The percentage-based band is superseded
    // because "you've already lost recall" is more urgent than "you're
    // 17% of the way to auto-compact".
    const baseClass = degraded
      ? 'text-red-100 bg-red-900/60 motion-safe:animate-flash-red'
      : bandClass(context.percentage, context.isAutoCompactEnabled);
    const title = degraded
      ? `Context: ${formatTokens(context.totalTokens)} / ` +
        `${formatTokens(context.maxTokens)} tokens ` +
        `(${context.percentage.toFixed(1)}%). ` +
        `Past 32K — recall degrades beyond this point. ` +
        `Auto-compact ${context.isAutoCompactEnabled ? 'on' : 'off'}.`
      : `Context: ${formatTokens(context.totalTokens)} / ` +
        `${formatTokens(context.maxTokens)} tokens ` +
        `(${context.percentage.toFixed(1)}%). ` +
        `Auto-compact ${context.isAutoCompactEnabled ? 'on' : 'off'}.`;
    return {
      class: baseClass,
      tokens: formatTokens(context.totalTokens),
      percent: `${Math.round(context.percentage)}%`,
      title
    };
  });
</script>

{#if pill}
  <span
    class="inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10px] {pill.class}"
    title={pill.title}
    aria-label={pill.title}
  >
    ctx {pill.tokens} ({pill.percent})
  </span>
{/if}
