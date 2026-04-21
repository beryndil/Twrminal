<script lang="ts">
  import type { Message } from '$lib/api';
  import type { LiveToolCall } from '$lib/stores/conversation.svelte';
  import { renderMarkdown } from '$lib/render';
  import { highlight } from '$lib/actions/highlight';
  import { stickToBottom } from '$lib/actions/autoscroll';

  type Props = {
    user: Message | null;
    assistant: Message | null;
    thinking: string;
    toolCalls: LiveToolCall[];
    streamingContent: string;
    streamingThinking: string;
    isStreaming: boolean;
    highlightQuery: string;
    copiedMsgId: string | null;
    onCopyMessage: (msg: Message) => void;
  };

  const {
    user,
    assistant,
    thinking,
    toolCalls,
    streamingContent,
    streamingThinking,
    isStreaming,
    highlightQuery,
    copiedMsgId,
    onCopyMessage
  }: Props = $props();

  const runningCount = $derived(toolCalls.filter((t) => t.ok === null).length);
  const thinkingCombined = $derived(thinking + streamingThinking);

  // Aggregate signal for the stick-to-bottom action: grows whenever a
  // new call appears or any existing call's output/error lengthens.
  const toolStreamSignal = $derived(
    toolCalls.reduce(
      (acc, c) => acc + (c.output?.length ?? 0) + (c.error?.length ?? 0),
      toolCalls.length
    )
  );

  function callMarker(ok: boolean | null): { glyph: string; cls: string } {
    if (ok === null) return { glyph: '●', cls: 'text-amber-400' };
    if (ok) return { glyph: '✓', cls: 'text-emerald-400' };
    return { glyph: '✗', cls: 'text-rose-400' };
  }
</script>

{#if user}
  <article class="rounded border border-slate-800 bg-slate-800/60 px-3 py-2">
    <header class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">user</header>
    <div class="prose prose-invert prose-sm max-w-none" use:highlight={highlightQuery}>
      {@html renderMarkdown(user.content)}
    </div>
  </article>
{/if}

{#if thinkingCombined}
  <details class="ml-6 rounded bg-slate-950/40 border border-slate-800/60 px-2 py-1">
    <summary class="cursor-pointer text-[10px] uppercase tracking-wider text-slate-500">
      thinking{isStreaming ? ' · live' : ''}
    </summary>
    <pre
      class="mt-1 whitespace-pre-wrap text-xs text-slate-400 font-sans">{thinkingCombined}</pre>
  </details>
{/if}

{#if toolCalls.length > 0}
  <details class="ml-6 rounded bg-slate-950/40 border border-slate-800/60 px-2 py-1">
    <summary
      class="cursor-pointer text-[10px] uppercase tracking-wider text-slate-500
        flex items-center gap-2"
    >
      <span>tool work · {toolCalls.length}</span>
      {#if runningCount > 0}
        <span class="bg-amber-900 text-amber-300 px-1.5 py-0.5 rounded text-[9px] uppercase">
          {runningCount} running
        </span>
      {/if}
    </summary>
    <div
      use:stickToBottom={toolStreamSignal}
      class="mt-2 max-h-80 overflow-y-auto rounded border border-slate-800
        bg-black/70 p-2 font-mono text-[10px] leading-relaxed text-slate-300"
    >
      {#each toolCalls as call, i (call.id)}
        {@const mark = callMarker(call.ok)}
        <pre
          class="whitespace-pre-wrap break-all {i > 0 ? 'mt-3' : ''}"><span
            class="text-emerald-400">$ {call.name}</span> <span
            class={mark.cls}>{mark.glyph}</span>{#if call.outputTruncated} <span
            class="text-amber-400">[truncated]</span>{/if}
{JSON.stringify(call.input, null, 2)}{#if call.output !== null}
{call.output}{/if}{#if call.error}
<span class="text-rose-400">error: {call.error}</span>{/if}</pre>
      {/each}
    </div>
  </details>
{/if}

{#if assistant || isStreaming}
  <article
    class="rounded border px-3 py-2 bg-slate-900
      {isStreaming ? 'border-amber-900/50' : 'border-slate-800'}"
  >
    <header
      class="text-[10px] uppercase tracking-wider mb-1
        {isStreaming ? 'text-amber-400' : 'text-slate-500'}"
    >
      assistant{isStreaming ? ' · streaming' : ''}
    </header>
    <div class="prose prose-invert prose-sm max-w-none" use:highlight={highlightQuery}>
      {#if assistant}
        {@html renderMarkdown(assistant.content)}
      {:else}
        {@html renderMarkdown(streamingContent)}
        <span class="inline-block animate-pulse">▍</span>
      {/if}
    </div>
    {#if assistant}
      <div class="mt-2 flex justify-end">
        <button
          type="button"
          class="text-[10px] uppercase tracking-wider text-slate-500 hover:text-slate-300"
          aria-label="Copy reply to clipboard"
          title={copiedMsgId === assistant.id ? 'Copied' : 'Copy reply'}
          onclick={() => onCopyMessage(assistant)}
        >
          {copiedMsgId === assistant.id ? '✓ copied' : '⎘ copy'}
        </button>
      </div>
    {/if}
  </article>
{/if}

