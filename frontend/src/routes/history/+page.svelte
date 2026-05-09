<script lang="ts">
  /**
   * ``/history`` route — placeholder pending the session-history phase.
   *
   * Closed sessions are accessible today via the sidebar's collapsed
   * "Closed" group. A dedicated history view with search and filtering
   * is planned for a future release. This stub satisfies SvelteKit
   * router registration so direct navigation to ``/history`` does not
   * 404 in-app.
   */
</script>

<svelte:head>
  <title>History — Bearings</title>
</svelte:head>

<div
  class="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
  data-testid="history-page"
>
  <h1 class="text-lg font-semibold text-fg-strong">History</h1>
  <p class="max-w-md text-sm text-fg-muted">
    Full session history with search and filtering — coming in a future release.
  </p>
</div>
