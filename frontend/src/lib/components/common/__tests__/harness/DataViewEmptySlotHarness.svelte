<script lang="ts">
  /** Test harness — DataView with a custom empty snippet override. */
  import DataView from "../../DataView.svelte";
</script>

<DataView isEmpty={true}>
  {#snippet empty()}
    <p data-testid="custom-empty-content">Custom empty content from slot.</p>
  {/snippet}
</DataView>
