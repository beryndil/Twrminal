<script lang="ts">
  import { undoStore } from '$lib/context-menu/undo.svelte';
  import UndoToast from './UndoToast.svelte';

  // Singleton host — mount once at the page root. Renders every
  // item in `undoStore` as a stacked UndoToast in the bottom-right.
  // Cap-at-3 is enforced by the store; this component just draws.
</script>

{#if undoStore.items.length > 0}
  <div
    class="fixed bottom-4 right-4 z-40 flex flex-col gap-2 items-end
      pointer-events-none"
    data-testid="undo-toast-host"
  >
    {#each undoStore.items as item (item.id)}
      <UndoToast {item} />
    {/each}
  </div>
{/if}
