<script lang="ts">
  /**
   * Lazy-mount wrapper for one entry in a long timeline.
   *
   * Backs the timeline virtualization landed for the
   * "Performance: timeline virtualization (post-refactor)" item.
   * The 2026-04-21 perf audit confirmed three of 41 historical
   * sessions already exceed 300 timeline items and the largest is
   * 580; opening one of those sessions paints every MessageTurn
   * (markdown + shiki + tool-call rendering) up front. This wrapper
   * lets the parent render-as-many-as-fit-the-viewport without
   * duplicating IntersectionObserver bookkeeping per call site.
   *
   * Mechanics:
   *   - When `forceVisible` is true the wrapper renders the slot
   *     unconditionally. Used for the streaming tail (in-place
   *     mutation requires mounted DOM) and a small "always-warm"
   *     band at the bottom of the timeline so the auto-scroll
   *     anchor is real content.
   *   - Otherwise an IntersectionObserver toggles `visible` based
   *     on viewport proximity (within `rootMarginPx` of the
   *     scrollable ancestor). When `visible=false` the wrapper
   *     reserves space with `min-height` so scroll position stays
   *     stable as items remount.
   *   - A ResizeObserver keeps `measuredHeight` synced with the
   *     real rendered height while the slot is mounted, so the
   *     placeholder uses the actual size after the first paint
   *     instead of the (deliberately conservative) fallback.
   *
   * Tradeoffs / known limits:
   *   - Browser ctrl+F can't find content inside a placeholder.
   *     Acceptable — the in-app search highlight already drives
   *     scroll-to-match before any user-typed find.
   *   - Off-screen items prepended via `loadOlder` mount as
   *     fallback-height placeholders before the ResizeObserver
   *     catches up. The existing scroll-anchor logic in
   *     `Conversation.svelte` (capture `prevHeight` → restore
   *     `scrollTop`) is robust to this because both reads happen
   *     during the same paint batch.
   */
  import type { Snippet } from 'svelte';

  type Props = {
    /** The scrollable ancestor used as the IntersectionObserver
     * root. When undefined the viewport is used — fine on first
     * paint, replaced once the parent's `bind:this` populates. */
    scrollRoot?: Element | null;
    /** Render the slot unconditionally. The parent flips this for
     * the streaming tail and for a few items above it so auto-
     * scroll has stable real DOM at the bottom. */
    forceVisible?: boolean;
    /** Distance above and below the viewport at which a placeholder
     * promotes to real content. Bigger = smoother scroll, more DOM
     * resident. Tuned so a single fast scroll-flick keeps content
     * mounted. */
    rootMarginPx?: number;
    /** Initial reserved height before this item has ever mounted.
     * The first ResizeObserver tick overwrites it with the real
     * height, so this only matters for the brief first frame and
     * for items that have never entered the viewport. Default
     * picks a roughly average MessageTurn size. */
    fallbackHeightPx?: number;
    children: Snippet;
  };

  const {
    scrollRoot = null,
    forceVisible = false,
    rootMarginPx = 1500,
    fallbackHeightPx = 180,
    children
  }: Props = $props();

  // The IntersectionObserver toggles `intersecting`. `noIO` flips
  // true in the unusual environment that lacks IntersectionObserver
  // entirely (some headless test runners) — without it we'd never
  // promote items to visible and the page would render blank.
  // `forceVisible` is OR'd in via `$derived` rather than written
  // into a writable state so the parent can reactively flip a turn
  // back to visible after culling without us needing a separate
  // "remember if forceVisible was ever true" flag.
  let intersecting = $state(false);
  let noIO = $state(false);
  let measuredHeight = $state<number | null>(null);
  let el: HTMLDivElement | undefined = $state();

  const visible = $derived(forceVisible || intersecting || noIO);
  // Until the ResizeObserver records a real height we reserve the
  // caller's fallback. This keeps the placeholder pixel-perfect
  // after the first paint and merely "close enough" before then.
  const placeholderHeight = $derived(measuredHeight ?? fallbackHeightPx);

  $effect(() => {
    if (forceVisible) return;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      // SSR / older test envs without IO. Fail open: render content
      // so the page is at least correct, even if not virtualized.
      noIO = true;
      return;
    }
    const target = el;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.target === target) intersecting = entry.isIntersecting;
        }
      },
      {
        root: scrollRoot ?? null,
        rootMargin: `${rootMarginPx}px 0px ${rootMarginPx}px 0px`
      }
    );
    io.observe(target);
    return () => io.disconnect();
  });

  $effect(() => {
    if (!visible) return;
    if (!el) return;
    if (typeof ResizeObserver === 'undefined') return;
    const target = el;
    const ro = new ResizeObserver(() => {
      const next = target.offsetHeight;
      if (next > 0) measuredHeight = next;
    });
    ro.observe(target);
    // Prime the measurement so the first frame after mount records
    // the real height before the next time we go offscreen.
    if (target.offsetHeight > 0) measuredHeight = target.offsetHeight;
    return () => ro.disconnect();
  });
</script>

<div
  bind:this={el}
  data-testid="virtual-item"
  data-visible={visible ? 'true' : 'false'}
  style:min-height={visible ? null : `${placeholderHeight}px`}
>
  {#if visible}{@render children()}{/if}
</div>
