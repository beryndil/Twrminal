<script lang="ts">
  /**
   * Test-only wrapper for `VirtualItem`. Snippets can't be passed
   * from a `render(...)` call directly, so the harness owns one
   * locally and threads through the VirtualItem props that the
   * tests want to drive. Kept inside `components/` (not under
   * `tests/`) so vitest's module resolution finds it without
   * extra config.
   */
  import VirtualItem from './VirtualItem.svelte';

  type Props = {
    label: string;
    forceVisible?: boolean;
    rootMarginPx?: number;
    fallbackHeightPx?: number;
    scrollRoot?: Element | null;
  };

  const {
    label,
    forceVisible = false,
    rootMarginPx,
    fallbackHeightPx,
    scrollRoot
  }: Props = $props();
</script>

<VirtualItem {forceVisible} {rootMarginPx} {fallbackHeightPx} {scrollRoot}>
  <div data-testid="cell-content">{label}</div>
</VirtualItem>
