<script lang="ts">
  import { conversation } from '$lib/stores/conversation.svelte';

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
</script>

<aside class="bg-slate-900 overflow-y-auto border-l border-slate-800 p-4 flex flex-col gap-3">
  <h2 class="text-sm uppercase tracking-wider text-slate-400">Inspector</h2>

  {#if conversation.toolCalls.length === 0}
    <p class="text-slate-500 text-sm">No tool calls yet.</p>
  {:else}
    <ul class="flex flex-col gap-3">
      {#each conversation.toolCalls as call (call.id)}
        {@const badge = statusBadge(call.ok)}
        <li class="rounded border border-slate-800 bg-slate-950/40 p-2 text-xs">
          <div class="flex items-center justify-between gap-2">
            <span class="font-mono font-medium truncate">{call.name}</span>
            <span class="{badge.classes} px-1.5 py-0.5 rounded text-[10px] uppercase">
              {badge.label}
            </span>
          </div>
          <div class="text-[10px] text-slate-500 mt-0.5">{elapsed(call.startedAt, call.finishedAt)}</div>

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
</aside>
