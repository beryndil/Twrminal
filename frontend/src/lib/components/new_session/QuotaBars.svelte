<script lang="ts">
  /**
   * Two-bar quota indicator (spec §4 + §8 + §10 — "two small bars:
   * overall remaining %, Sonnet remaining %. Yellow at 80% used,
   * red at 95%"). Used inside the new-session dialog (item 2.4 /
   * spec §6 layout) and — by the same component — in the session
   * header in subsequent items.
   *
   * The component is purely presentational: the parent feeds it the
   * already-fetched snapshot (or ``null`` when no data is available
   * yet). That keeps the component testable without mocking ``fetch``
   * twice — the new-session dialog tests its fetch path once at the
   * dialog level.
   *
   * Threshold colours come from the mirrored backend constants
   * :data:`QUOTA_BAR_YELLOW_PCT` (0.80) and :data:`QUOTA_BAR_RED_PCT`
   * (0.95) so a coding-standards review can grep one source of truth.
   */
  import { NEW_SESSION_STRINGS, QUOTA_BAR_RED_PCT, QUOTA_BAR_YELLOW_PCT } from "../../config";

  /**
   * Snapshot of the two relevant bucket states (spec §4). ``null`` on
   * either field means "the upstream /usage payload didn't include
   * this bucket"; the bar renders as unavailable rather than 0 %.
   */
  export interface QuotaBarsSnapshot {
    overallUsedPct: number | null;
    sonnetUsedPct: number | null;
    overallResetsAt: number | null;
    sonnetResetsAt: number | null;
  }

  interface Props {
    snapshot: QuotaBarsSnapshot | null;
  }

  const { snapshot }: Props = $props();

  type Severity = "ok" | "yellow" | "red" | "unknown";

  function severity(usedPct: number | null): Severity {
    if (usedPct === null) {
      return "unknown";
    }
    if (usedPct >= QUOTA_BAR_RED_PCT) {
      return "red";
    }
    if (usedPct >= QUOTA_BAR_YELLOW_PCT) {
      return "yellow";
    }
    return "ok";
  }

  /** Used → remaining, clamped to ``[0, 1]`` so a glitched payload doesn't render past the track. */
  function remainingPct(usedPct: number | null): number {
    if (usedPct === null) {
      return 0;
    }
    const remaining = 1 - usedPct;
    if (remaining < 0) return 0;
    if (remaining > 1) return 1;
    return remaining;
  }

  function pctText(usedPct: number | null): string {
    if (usedPct === null) return "—";
    return `${Math.round(usedPct * 100)}%`;
  }

  function resetTooltip(resetsAt: number | null): string | undefined {
    if (resetsAt === null) return undefined;
    const date = new Date(resetsAt * 1000);
    return `${NEW_SESSION_STRINGS.quotaResetTooltipPrefix} ${date.toLocaleString()}`;
  }

  const overallSeverity = $derived(severity(snapshot?.overallUsedPct ?? null));
  const sonnetSeverity = $derived(severity(snapshot?.sonnetUsedPct ?? null));
  const overallRemaining = $derived(remainingPct(snapshot?.overallUsedPct ?? null));
  const sonnetRemaining = $derived(remainingPct(snapshot?.sonnetUsedPct ?? null));
</script>

<div class="quota-bars" data-testid="quota-bars">
  <h3 class="quota-bars__heading">{NEW_SESSION_STRINGS.quotaHeading}</h3>
  {#if snapshot === null}
    <p class="quota-bars__unavailable" data-testid="quota-bars-unavailable">
      {NEW_SESSION_STRINGS.quotaUnavailable}
    </p>
  {:else}
    <div
      class="quota-bars__row"
      data-testid="quota-bar-overall"
      data-severity={overallSeverity}
      title={resetTooltip(snapshot.overallResetsAt)}
    >
      <span class="quota-bars__label">{NEW_SESSION_STRINGS.quotaOverallLabel}</span>
      <span
        class="quota-bars__track"
        role="progressbar"
        aria-label={NEW_SESSION_STRINGS.quotaOverallLabel}
        aria-valuenow={Math.round((snapshot.overallUsedPct ?? 0) * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span
          class="quota-bars__fill"
          style:width={`${Math.round(overallRemaining * 100)}%`}
          data-testid="quota-bar-overall-fill"
        ></span>
      </span>
      <span class="quota-bars__pct" data-testid="quota-bar-overall-pct">
        {pctText(snapshot.overallUsedPct)}
      </span>
    </div>
    <div
      class="quota-bars__row"
      data-testid="quota-bar-sonnet"
      data-severity={sonnetSeverity}
      title={resetTooltip(snapshot.sonnetResetsAt)}
    >
      <span class="quota-bars__label">{NEW_SESSION_STRINGS.quotaSonnetLabel}</span>
      <span
        class="quota-bars__track"
        role="progressbar"
        aria-label={NEW_SESSION_STRINGS.quotaSonnetLabel}
        aria-valuenow={Math.round((snapshot.sonnetUsedPct ?? 0) * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span
          class="quota-bars__fill"
          style:width={`${Math.round(sonnetRemaining * 100)}%`}
          data-testid="quota-bar-sonnet-fill"
        ></span>
      </span>
      <span class="quota-bars__pct" data-testid="quota-bar-sonnet-pct">
        {pctText(snapshot.sonnetUsedPct)}
      </span>
    </div>
  {/if}
</div>

<style>
  .quota-bars {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .quota-bars__heading {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .quota-bars__unavailable {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .quota-bars__row {
    display: grid;
    grid-template-columns: 4rem 1fr 3rem;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
  }
  .quota-bars__label {
    color: rgb(var(--bearings-fg-muted));
  }
  .quota-bars__track {
    display: block;
    height: 0.5rem;
    background: rgb(var(--bearings-surface-2));
    border-radius: 9999px;
    overflow: hidden;
  }
  .quota-bars__fill {
    display: block;
    height: 100%;
    background: #4ade80;
    transition: width 200ms ease;
  }
  .quota-bars__row[data-severity="yellow"] .quota-bars__fill {
    background: #facc15;
  }
  .quota-bars__row[data-severity="red"] .quota-bars__fill {
    background: #ef4444;
  }
  .quota-bars__row[data-severity="unknown"] .quota-bars__fill {
    background: #888;
  }
  .quota-bars__pct {
    text-align: right;
    color: rgb(var(--bearings-fg-muted));
    font-variant-numeric: tabular-nums;
  }
</style>
