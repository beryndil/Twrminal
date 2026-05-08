<script lang="ts">
  /** Test harness — DataView in the error state with a retry callback. */
  import DataView from "../../DataView.svelte";

  let _retries = $state(0);
</script>

<DataView
  error="Test error message"
  onretry={() => {
    _retries += 1;
  }}
/>
