<script lang="ts">
  /**
   * ``/dashboard`` route — placeholder pending the dashboard phase.
   *
   * Satisfies SvelteKit router registration so direct navigation to
   * ``/dashboard`` does not 404 in-app. Body will be replaced when the
   * dashboard feature ships.
   */
</script>

<svelte:head>
  <title>Dashboard — Bearings</title>
</svelte:head>

<div
  class="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
  data-testid="dashboard-page"
>
  <h1 class="text-lg font-semibold text-fg-strong">Dashboard</h1>
  <p class="max-w-md text-sm text-fg-muted">
    Session analytics and quick-start overview — coming in a future release.
  </p>
</div>
