<script lang="ts">
  /** Test harness — VirtualItem wrapping a single content div. */
  import VirtualItem from "../../VirtualItem.svelte";
</script>

<VirtualItem>
  <div data-testid="virtual-item-test-content">Test content</div>
</VirtualItem>
