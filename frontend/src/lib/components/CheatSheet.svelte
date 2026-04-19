<script lang="ts">
  let { open = $bindable(false) }: { open?: boolean } = $props();

  type Shortcut = { keys: string[]; description: string };

  const shortcuts: { group: string; items: Shortcut[] }[] = [
    {
      group: 'Navigation',
      items: [
        { keys: ['⌘/Ctrl', 'K'], description: 'Focus the sidebar search' },
        { keys: ['Esc'], description: 'Clear search / close the search' },
        { keys: ['?'], description: 'Show this cheat sheet' }
      ]
    },
    {
      group: 'Conversation',
      items: [
        { keys: ['Enter'], description: 'Send the prompt' },
        { keys: ['Shift', 'Enter'], description: 'Newline inside the prompt' },
        { keys: ['Esc'], description: 'Clear an active search highlight' }
      ]
    },
    {
      group: 'Sessions',
      items: [
        { keys: ['Double-click', 'title'], description: 'Rename a session' },
        { keys: ['✎'], description: 'Edit title or budget in the header' },
        { keys: ['⚙'], description: 'Open Settings (token + defaults)' },
        { keys: ['✕'], description: 'Delete a session (click twice to confirm)' }
      ]
    }
  ];

  function onCancel() {
    open = false;
  }
</script>

{#if open}
  <div class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4">
    <div
      class="w-full max-w-md rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl
        flex flex-col gap-4"
    >
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-medium">Shortcuts</h2>
          <p class="text-xs text-slate-400 mt-1">
            Esc or <kbd class="kbd">?</kbd> to close.
          </p>
        </div>
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Close cheat sheet"
          onclick={onCancel}
        >
          ✕
        </button>
      </header>

      <div class="flex flex-col gap-4 text-sm">
        {#each shortcuts as group (group.group)}
          <section>
            <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
              {group.group}
            </h3>
            <ul class="flex flex-col gap-1">
              {#each group.items as sc}
                <li class="flex items-baseline justify-between gap-3">
                  <span class="text-slate-300">{sc.description}</span>
                  <span class="flex gap-1 shrink-0">
                    {#each sc.keys as k}
                      <kbd class="kbd">{k}</kbd>
                    {/each}
                  </span>
                </li>
              {/each}
            </ul>
          </section>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .kbd {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.6875rem;
    background-color: rgb(15 23 42);
    color: rgb(226 232 240);
    border: 1px solid rgb(51 65 85);
    border-radius: 0.25rem;
    padding: 0.05rem 0.35rem;
  }
</style>
