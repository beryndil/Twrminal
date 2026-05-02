<script lang="ts">
  /**
   * ``/analytics`` route — usage + quota rollups for the v1 instance.
   *
   * Replaces the v1.0 stub ('Per-instance analytics are coming in a
   * follow-up phase') flagged by the closing-sweep audit (2026-05-02,
   * P1.8). Reuses :class:`InspectorUsage` — the per-session inspector
   * tab already renders every spec §10 widget (headroom chart,
   * by-model table, advisor effectiveness, rules-to-review) against
   * app-wide data, so the standalone page just hosts the same
   * component without a session prop.
   *
   * Backend endpoints exercised (all live since item 1.8):
   *
   * - ``GET /api/quota/history?days=7``
   * - ``GET /api/usage/by_model?period=week``
   * - ``GET /api/usage/override_rates?days=14``
   */
  import InspectorUsage from "$lib/components/inspector/InspectorUsage.svelte";
</script>

<section class="analytics-page" data-testid="analytics-page" aria-label="Usage analytics">
  <header class="analytics-page__header">
    <h1>Analytics</h1>
    <p class="analytics-page__lede">
      App-wide quota headroom, per-model token totals, advisor effectiveness, and rules whose
      override rate has crossed the review threshold (spec §8 + §10).
    </p>
  </header>
  <InspectorUsage />
</section>

<style>
  .analytics-page {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    max-width: 64rem;
    margin: 0 auto;
    overflow-y: auto;
  }
  .analytics-page__header h1 {
    font-size: 1.25rem;
    font-weight: 600;
    margin: 0;
  }
  .analytics-page__lede {
    font-size: 0.875rem;
    color: var(--fg-muted, #888);
    margin: 0.25rem 0 0 0;
  }
</style>
