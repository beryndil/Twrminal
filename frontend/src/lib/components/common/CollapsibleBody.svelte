<script lang="ts">
  /**
   * Collapsible wrapper for long content — message bodies and
   * tool-output streams.
   *
   * When the natural content height exceeds ``thresholdPx`` the wrapper
   * clamps to that height, fades the last
   * :data:`COLLAPSIBLE_BODY_FADE_PX` pixels with a CSS mask-image, and
   * shows a "Show full" button beneath. Clicking it expands the wrapper
   * to natural height and replaces the button with a "Collapse"
   * affordance.
   *
   * Once expanded the wrapper does not re-collapse on scroll — only the
   * explicit "Collapse" button contracts it again.
   *
   * A :class:`ResizeObserver` watches the inner content element so that
   * streaming output and theme-driven font swaps re-evaluate the fold
   * threshold without requiring a component re-render.
   *
   * Behavior anchor:
   * ``docs/behavior/chat.md`` §"CollapsibleBody".
   *
   * Used by:
   * - ``MessageTurn`` — assistant message body.
   * - ``ToolOutput`` — output stream area.
   */
  import type { Snippet } from "svelte";
  import {
    COLLAPSIBLE_BODY_FADE_PX,
    COLLAPSIBLE_BODY_STRINGS,
    COLLAPSIBLE_BODY_THRESHOLD_PX,
  } from "../../config";

  interface Props {
    /** Content slot. */
    children?: Snippet;
    /**
     * Height threshold in pixels. Content whose natural height exceeds
     * this value triggers the fold UI. Defaults to
     * :data:`COLLAPSIBLE_BODY_THRESHOLD_PX`.
     */
    thresholdPx?: number;
    /** Extra CSS classes forwarded to the outer wrapper element. */
    class?: string;
  }

  const {
    children,
    thresholdPx = COLLAPSIBLE_BODY_THRESHOLD_PX,
    class: extraClass = "",
  }: Props = $props();

  /** Reference to the inner content element — the ResizeObserver target. */
  let contentEl = $state<HTMLDivElement | null>(null);

  /**
   * True when the content's natural height exceeds ``thresholdPx``.
   * Updated by the ResizeObserver on every size change.
   */
  let overThreshold = $state(false);

  /**
   * True after the user has clicked "Show full". Remains true until the
   * user explicitly clicks "Collapse" — scrolling does not re-fold.
   */
  let expanded = $state(false);

  /**
   * Wire a ResizeObserver to the inner content element. On every size
   * change, re-evaluate whether the content height still exceeds the
   * threshold so that streaming output crosses the fold boundary
   * smoothly. Cleaned up on unmount.
   */
  $effect(() => {
    if (contentEl === null) return;
    const el = contentEl;

    const observer = new ResizeObserver((entries: ResizeObserverEntry[]) => {
      const entry = entries[0];
      if (entry === undefined) return;
      overThreshold = entry.contentRect.height > thresholdPx;
    });

    observer.observe(el);

    return () => {
      observer.disconnect();
    };
  });

  function expand(): void {
    expanded = true;
  }

  function collapse(): void {
    expanded = false;
  }

  /**
   * Inline style string for the clamping wrapper. Applied when the
   * content is folded and over the threshold. Empty string otherwise so
   * the element renders at natural height with no extra constraints.
   */
  const clampStyle = $derived(
    !expanded && overThreshold
      ? `max-height: ${thresholdPx}px; overflow: hidden; ` +
          `mask-image: linear-gradient(to bottom, black calc(100% - ${COLLAPSIBLE_BODY_FADE_PX}px), transparent 100%); ` +
          `-webkit-mask-image: linear-gradient(to bottom, black calc(100% - ${COLLAPSIBLE_BODY_FADE_PX}px), transparent 100%);`
      : "",
  );
</script>

<!--
  Outer wrapper: receives the clamping style (max-height + overflow +
  mask-image) when the content is folded and over the threshold.

  Inner div (bind:this={contentEl}): the ResizeObserver target. It has
  no size constraints of its own, so it always lays out at the content's
  natural height. The outer wrapper's overflow:hidden clips the rendered
  output without affecting the inner element's reported height — which
  is what lets the observer correctly detect "still over threshold" even
  while the content is folded.
-->
<div class="collapsible-body {extraClass}">
  <div
    style={clampStyle}
    data-testid="collapsible-body-inner"
    data-over-threshold={overThreshold}
    data-expanded={expanded}
  >
    <div bind:this={contentEl} data-testid="collapsible-body-content">
      {@render children?.()}
    </div>
  </div>
  {#if overThreshold}
    {#if !expanded}
      <button
        type="button"
        class="collapsible-body__show mt-1 text-xs text-accent hover:underline"
        data-testid="collapsible-body-show"
        onclick={expand}
      >
        {COLLAPSIBLE_BODY_STRINGS.showFull}
      </button>
    {:else}
      <button
        type="button"
        class="collapsible-body__collapse mt-1 text-xs text-fg-muted hover:underline"
        data-testid="collapsible-body-collapse"
        onclick={collapse}
      >
        {COLLAPSIBLE_BODY_STRINGS.collapse}
      </button>
    {/if}
  {/if}
</div>
