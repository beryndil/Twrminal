<script lang="ts">
  /**
   * Story-style development harness for ``DataView`` (gap-cycle-01-011).
   *
   * Renders a control strip that toggles ``DataView`` through all four
   * states — loading / error / empty / success — without requiring a
   * live data source. Import this component in a dev route or Storybook
   * story to exercise every branch of the wrapper.
   *
   * Usage:
   * ```svelte
   * <DataViewHarness />
   * ```
   *
   * The active state is driven entirely by ``$state`` runes; no external
   * props are required. An ``onretry`` stub is wired so the retry button
   * is always rendered in the error state.
   */
  import DataView from "./DataView.svelte";

  type HarnessState = "loading" | "error" | "empty" | "success";

  let activeState = $state<HarnessState>("success");

  const states: HarnessState[] = ["loading", "error", "empty", "success"];

  const loading = $derived(activeState === "loading");
  const error = $derived<string | null>(
    activeState === "error" ? "Example fetch error from harness." : null,
  );
  const isEmpty = $derived(activeState === "empty");

  let retryCount = $state(0);

  function handleRetry(): void {
    retryCount += 1;
  }
</script>

<div class="data-view-harness flex flex-col gap-4 p-4" data-testid="data-view-harness">
  <!-- State selector strip -->
  <div class="flex flex-row gap-2" data-testid="data-view-harness-controls">
    {#each states as state (state)}
      <button
        type="button"
        class="rounded border px-2 py-1 text-xs"
        class:border-accent={activeState === state}
        class:text-accent={activeState === state}
        class:border-border={activeState !== state}
        class:text-fg-muted={activeState !== state}
        data-testid="data-view-harness-btn-{state}"
        onclick={() => {
          activeState = state;
        }}
      >
        {state}
      </button>
    {/each}
  </div>

  <!-- Active state label -->
  <p class="text-xs text-fg-muted" data-testid="data-view-harness-state-label">
    State: <span class="font-mono text-fg">{activeState}</span>
    {#if retryCount > 0}
      · retries: {retryCount}
    {/if}
  </p>

  <!-- DataView under test -->
  <div class="rounded border border-border" data-testid="data-view-harness-target">
    <DataView {loading} {error} {isEmpty} onretry={handleRetry}>
      {#snippet empty()}
        <p class="text-sm text-fg-muted" data-testid="data-view-harness-empty-slot">
          No items to display (harness empty slot).
        </p>
      {/snippet}
      <!-- Default slot: success content -->
      <p class="p-2 text-sm text-fg" data-testid="data-view-harness-success-content">
        Success — data loaded. Replace this with your real content.
      </p>
    </DataView>
  </div>
</div>
