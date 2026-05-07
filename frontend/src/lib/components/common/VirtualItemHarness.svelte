<script lang="ts">
  /**
   * Story-style development harness for ``VirtualItem`` (gap-cycle-01-012).
   *
   * Mounts a synthetic 1 000-row list inside a fixed-height scrollable
   * container so developers can observe row mount/unmount behaviour in
   * the browser without a live data source. As you scroll, rows outside
   * the 200 px preload margin are replaced by fixed-height placeholders
   * and rows approaching the viewport are re-mounted.
   *
   * Usage:
   * ```svelte
   * <VirtualItemHarness />
   * ```
   *
   * No external props are required.
   */
  import VirtualItem from "./VirtualItem.svelte";

  /** Number of synthetic rows to render. */
  const ROW_COUNT = 1000;

  const rows = Array.from({ length: ROW_COUNT }, (_, i) => i);
</script>

<div class="virtual-item-harness flex flex-col gap-2 p-4" data-testid="virtual-item-harness">
  <p class="text-sm text-fg-muted">
    {ROW_COUNT}-row synthetic list. Rows outside the 200 px scroll margin are virtualised.
  </p>

  <div
    class="overflow-y-auto rounded border border-border"
    style="height: 400px"
    data-testid="virtual-item-harness-scroll"
  >
    {#each rows as row (row)}
      <VirtualItem>
        <div
          class="virtual-item-harness__row border-b border-border px-3 py-2 text-sm text-fg"
          data-testid="virtual-item-harness-row"
        >
          Row {row + 1}
        </div>
      </VirtualItem>
    {/each}
  </div>
</div>
