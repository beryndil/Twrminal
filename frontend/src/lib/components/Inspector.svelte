<script lang="ts">
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';

  function statusBadge(ok: boolean | null): { label: string; classes: string } {
    if (ok === null) return { label: 'running', classes: 'bg-amber-900 text-amber-300' };
    if (ok) return { label: 'ok', classes: 'bg-emerald-900 text-emerald-300' };
    return { label: 'error', classes: 'bg-rose-900 text-rose-300' };
  }

  function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function elapsed(startedAt: number, finishedAt: number | null): string {
    if (finishedAt === null) return 'running';
    return formatDuration(finishedAt - startedAt);
  }

  let agentOpen = $state(true);
  let scrollContainer: HTMLElement | undefined = $state();
  const running = $derived(
    conversation.toolCalls.filter((t) => t.ok === null).length
  );

  // Auto-follow scroll to the latest tool call while the agent is
  // actively streaming and the agent disclosure is open. `tick`
  // guarantees the new row is in the DOM before we measure.
  $effect(() => {
    // Track the number of tool calls + active streaming so the effect
    // reruns on every new arrival.
    void conversation.toolCalls.length;
    void conversation.streamingActive;
    if (!scrollContainer || !agentOpen) return;
    if (!conversation.streamingActive) return;
    queueMicrotask(() => {
      if (!scrollContainer) return;
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    });
  });
</script>

<aside
  bind:this={scrollContainer}
  class="bg-slate-900 overflow-y-auto border-l border-slate-800 p-4 flex flex-col gap-3"
>
  <details class="agent-group" bind:open={agentOpen}>
    <summary class="flex items-baseline justify-between gap-2 cursor-pointer">
      <span class="text-sm uppercase tracking-wider text-slate-400">
        Agent
      </span>
      <span class="text-[10px] text-slate-500 font-mono truncate">
        {#if sessions.selected}
          {sessions.selected.model}
        {/if}
      </span>
    </summary>

    <div class="mt-2 text-[11px] text-slate-500 flex items-center gap-2">
      <span>{conversation.toolCalls.length} tool call{conversation.toolCalls.length === 1 ? '' : 's'}</span>
      {#if running > 0}
        <span class="bg-amber-900 text-amber-300 px-1.5 py-0.5 rounded text-[9px] uppercase">
          {running} running
        </span>
      {/if}
    </div>

    {#if conversation.toolCalls.length === 0}
      <p class="text-slate-500 text-sm mt-3">No tool calls yet.</p>
    {:else}
      <ul class="flex flex-col gap-2 mt-3">
        {#each conversation.toolCalls as call (call.id)}
          {@const badge = statusBadge(call.ok)}
          <li class="rounded border border-slate-800 bg-slate-950/40 p-2 text-xs">
            <div class="flex items-center justify-between gap-2">
              <span class="font-mono font-medium truncate">{call.name}</span>
              <span class="{badge.classes} px-1.5 py-0.5 rounded text-[10px] uppercase">
                {badge.label}
              </span>
            </div>
            <div class="text-[10px] text-slate-500 mt-0.5">
              {elapsed(call.startedAt, call.finishedAt)}
            </div>

            <details class="mt-2">
              <summary class="cursor-pointer text-slate-400 text-[11px]">input</summary>
              <pre
                class="mt-1 text-[10px] text-slate-300 whitespace-pre-wrap break-all">{JSON.stringify(
                  call.input,
                  null,
                  2
                )}</pre>
            </details>

            {#if call.output !== null}
              <details class="mt-1">
                <summary class="cursor-pointer text-slate-400 text-[11px]">output</summary>
                <pre
                  class="mt-1 text-[10px] text-slate-300 whitespace-pre-wrap break-all">{call.output}</pre>
              </details>
            {/if}

            {#if call.error}
              <div class="mt-1 rounded bg-rose-950/40 p-1.5">
                <div class="text-[10px] uppercase text-rose-400">error</div>
                <pre
                  class="text-[10px] text-rose-200 whitespace-pre-wrap break-all">{call.error}</pre>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </details>
</aside>

<style>
  /* Hide the default details arrow; we carry the disclosure affordance
   * in the summary layout itself. */
  .agent-group > summary {
    list-style: none;
  }
  .agent-group > summary::-webkit-details-marker {
    display: none;
  }
  /* Small chevron glyph on the summary so the collapse is discoverable. */
  .agent-group > summary::before {
    content: '▾';
    color: rgb(100 116 139);
    font-size: 0.75rem;
    margin-right: 0.4rem;
  }
  .agent-group:not([open]) > summary::before {
    content: '▸';
  }
</style>
