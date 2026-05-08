<script lang="ts">
  /**
   * Shared data-fetching wrapper (gap-cycle-01-011).
   *
   * Routes every data-fetching view through one consistent set of
   * loading / error / empty / success states so the user sees a
   * uniform skeleton, error state with retry, and empty-state copy
   * across every surface — per Beryndil standards §9 Error UX.
   *
   * State priority (evaluated in order):
   * 1. ``loading`` → skeleton placeholder.
   * 2. ``error`` (non-null/non-empty) → error message + retry button.
   * 3. ``isEmpty`` → empty-state copy (overridable via ``empty`` snippet).
   * 4. Default → ``children`` slot (success body).
   *
   * Named snippets ``empty`` and ``errorContent`` let consumers
   * override the default empty and error rendering while retaining the
   * state-machine dispatch logic.
   *
   * Behaviour anchor: ``docs/behavior/`` §"Error UX".
   */
  import type { Snippet } from "svelte";
  import { DATA_VIEW_STRINGS } from "../../config";

  interface Props {
    /** True while a fetch is in flight. Renders the loading skeleton. */
    loading?: boolean;
    /**
     * Non-null / non-empty string signals a fetch failure.
     * Renders the error state with the supplied message (or
     * :data:`DATA_VIEW_STRINGS.errorFallback` when the string is empty).
     */
    error?: string | null;
    /** True when the fetch succeeded but the result set is empty. */
    isEmpty?: boolean;
    /**
     * Callback wired to the retry button in the default error state.
     * When omitted the retry button is hidden.
     */
    onretry?: () => void;
    /** Success body — rendered only when not loading, not errored, not empty. */
    children?: Snippet;
    /** Override snippet for the empty state. Replaces the default copy. */
    empty?: Snippet;
    /**
     * Override snippet for the error state.
     * Receives the resolved error message string.
     */
    errorContent?: Snippet<[string]>;
  }

  const {
    loading = false,
    error = null,
    isEmpty = false,
    onretry,
    children,
    empty,
    errorContent,
  }: Props = $props();

  /** Resolved error message — falls back to the default copy string. */
  const errorMessage = $derived(
    error !== null && error !== undefined && error !== "" ? error : DATA_VIEW_STRINGS.errorFallback,
  );

  /** True when the error prop signals a failure (non-null and non-empty). */
  const hasError = $derived(error !== null && error !== undefined && error !== "");
</script>

{#if loading}
  <!--
    Deterministic loading skeleton — three static placeholder bars of
    fixed widths. No random shimmer phase; the structure is identical
    on every render so snapshot tests are stable.
  -->
  <div
    class="data-view data-view--loading flex flex-col gap-2 p-2"
    data-testid="data-view-loading"
    aria-label={DATA_VIEW_STRINGS.loadingAriaLabel}
    aria-busy="true"
    role="status"
  >
    <div
      class="data-view__skeleton-bar h-3 w-3/4 rounded bg-surface-2 opacity-60"
      data-testid="data-view-skeleton-bar"
    ></div>
    <div
      class="data-view__skeleton-bar h-3 w-1/2 rounded bg-surface-2 opacity-60"
      data-testid="data-view-skeleton-bar"
    ></div>
    <div
      class="data-view__skeleton-bar h-3 w-2/3 rounded bg-surface-2 opacity-60"
      data-testid="data-view-skeleton-bar"
    ></div>
  </div>
{:else if hasError}
  <div
    class="data-view data-view--error flex flex-col gap-2 p-2"
    data-testid="data-view-error"
    aria-label={DATA_VIEW_STRINGS.errorAriaLabel}
    role="alert"
  >
    {#if errorContent !== undefined}
      {@render errorContent(errorMessage)}
    {:else}
      <p
        class="data-view__error-message text-sm text-red-400"
        data-testid="data-view-error-message"
      >
        {errorMessage}
      </p>
      {#if onretry !== undefined}
        <button
          type="button"
          class="data-view__retry self-start rounded border border-border bg-surface-2 px-2 py-1 text-xs text-fg hover:bg-surface-1"
          data-testid="data-view-retry"
          onclick={onretry}
        >
          {DATA_VIEW_STRINGS.retryLabel}
        </button>
      {/if}
    {/if}
  </div>
{:else if isEmpty}
  <div
    class="data-view data-view--empty p-2"
    data-testid="data-view-empty"
    aria-label={DATA_VIEW_STRINGS.emptyAriaLabel}
  >
    {#if empty !== undefined}
      {@render empty()}
    {:else}
      <p class="text-sm text-fg-muted" data-testid="data-view-empty-default">
        {DATA_VIEW_STRINGS.emptyFallback}
      </p>
    {/if}
  </div>
{:else}
  <div class="data-view data-view--success" data-testid="data-view-success">
    {@render children?.()}
  </div>
{/if}
