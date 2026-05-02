<script lang="ts">
  /**
   * In-dialog "Routed from..." line — the human-readable reason
   * line that sits directly below the executor / advisor / effort
   * selectors per spec §6 layout. Updates reactively as the parent
   * re-runs the debounced ``/api/routing/preview`` fetch.
   *
   * Renders one of:
   *
   * * ``Routed from <reason>`` — when the parent has a fresh preview;
   * * ``Manual override`` — when the user has touched the routing
   *   selectors after the last preview (spec §6 — "the routed-from
   *   line changes to 'Manual override'");
   * * ``Resolving routing…`` — while the debounced fetch is in
   *   flight (no preview yet);
   * * ``Couldn't resolve routing — try again.`` — when the last
   *   fetch raised an error (spec is silent on copy here; a
   *   neutral failure-state phrasing rather than spinning forever).
   *
   * Per arch: presentational only. The parent owns the state
   * transitions; this component just maps state → DOM.
   */
  import { NEW_SESSION_STRINGS } from "../../config";

  /** Discriminated state union (parent owns the transitions). */
  export type RoutingPreviewState =
    | { kind: "loading" }
    | { kind: "manual" }
    | { kind: "ready"; reason: string }
    | { kind: "error" };

  interface Props {
    state: RoutingPreviewState;
  }

  const { state }: Props = $props();
</script>

<p class="routing-preview" data-testid="routing-preview" data-kind={state.kind}>
  {#if state.kind === "loading"}
    {NEW_SESSION_STRINGS.loadingPreview}
  {:else if state.kind === "manual"}
    {NEW_SESSION_STRINGS.routedManualOverride}
  {:else if state.kind === "ready"}
    {NEW_SESSION_STRINGS.routedFromPrefix} {state.reason}
  {:else if state.kind === "error"}
    {NEW_SESSION_STRINGS.previewError}
  {/if}
</p>

<style>
  .routing-preview {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0.25rem 0;
  }
  .routing-preview[data-kind="manual"] {
    color: rgb(var(--bearings-accent));
  }
  .routing-preview[data-kind="error"] {
    color: #ef4444;
  }
</style>
