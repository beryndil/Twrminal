<script lang="ts">
  import { stubStore } from '$lib/context-menu/stub.svelte';
  import StubToast from './StubToast.svelte';

  // Singleton host for "Not yet implemented" toasts. Stacks below
  // the undo toast host (bottom-right, above Undo stack) so the two
  // don't collide — both are bottom-anchored but the stub stack
  // sits a row higher.
</script>

{#if stubStore.items.length > 0}
  <div
    class="fixed bottom-24 right-4 z-40 flex flex-col gap-2 items-end
      pointer-events-none"
    data-testid="stub-toast-host"
  >
    {#each stubStore.items as item (item.id)}
      <StubToast {item} />
    {/each}
  </div>
{/if}
