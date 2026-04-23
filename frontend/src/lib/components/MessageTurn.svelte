<script lang="ts">
  import type { Message } from '$lib/api';
  import type { LiveToolCall } from '$lib/stores/conversation.svelte';
  import { stickToBottom } from '$lib/actions/autoscroll';
  import { contextmenu } from '$lib/actions/contextmenu';
  import CollapsibleBody from './CollapsibleBody.svelte';

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
    /** Slice 4: bulk-select mode. When `bulkMode` is true the header
     * renders a checkbox in place of the ordinary role tag and the
     * context-menu action is still wired — right-click while in bulk
     * mode lands on the message registry, same as normal. `selectedIds`
     * is the live set; toggling a row fires `onToggleSelect` with the
     * message and whether Shift was held (for range selection, handled
     * by the parent). */
    bulkMode?: boolean;
    selectedIds?: ReadonlySet<string>;
    onToggleSelect?: (msg: Message, shiftKey: boolean) => void;
  };

  /**
   * Phase 5 removed the `⋯` header popover. Move-to-session and
   * Split-here used to live inside it; those actions now fire from the
   * right-click registry (`actions/message.ts`) and publish to the
   * `reorgStore` bridge so `Conversation.svelte` opens its picker.
   * Existing callers that used to pass `onMoveMessage` / `onSplitAfter`
   * no longer need the prop — the actions reach Conversation through
   * the store instead.
   */
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
    onCopyMessage,
    bulkMode = false,
    selectedIds,
    onToggleSelect
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

  function isSelected(id: string): boolean {
    return selectedIds?.has(id) ?? false;
  }

  function onCheckboxClick(e: MouseEvent, msg: Message) {
    // The checkbox itself is triggered by the browser before this
    // handler fires; we intercept to deliver the shiftKey flag to
    // the parent so shift-click-range logic lives in one place.
    e.preventDefault();
    onToggleSelect?.(msg, e.shiftKey);
  }
</script>

{#if user}
  <article
    class="relative rounded border px-3 py-2 group
      {bulkMode && isSelected(user.id)
        ? 'border-emerald-500 bg-emerald-900/10'
        : user.pinned
          ? 'border-amber-500/60 bg-slate-800/60'
          : 'border-slate-800 bg-slate-800/60'}
      {user.hidden_from_context ? 'opacity-50' : ''}"
    data-testid="user-article"
    data-message-id={user.id}
    data-pinned={user.pinned ? 'true' : 'false'}
    data-hidden-from-context={user.hidden_from_context ? 'true' : 'false'}
    use:contextmenu={{
      target: {
        type: 'message',
        id: user.id,
        sessionId: user.session_id,
        role: 'user'
      }
    }}
  >
    <header
      class="flex items-center justify-between text-[10px] uppercase tracking-wider
        text-slate-500 mb-1"
    >
      <span class="flex items-center gap-2">
        {#if bulkMode}
          <input
            type="checkbox"
            class="accent-emerald-500 cursor-pointer"
            aria-label={`Select user message ${user.id}`}
            checked={isSelected(user.id)}
            onclick={(e) => onCheckboxClick(e, user!)}
            data-testid="bulk-checkbox"
            data-message-id={user.id}
          />
        {/if}
        <span>user</span>
        {#if user.pinned}
          <span class="text-amber-400 normal-case" title="Pinned">📌</span>
        {/if}
        {#if user.hidden_from_context}
          <span class="text-slate-500 normal-case" title="Hidden from context window"
            >👁‍🗨 hidden</span
          >
        {/if}
      </span>
    </header>
    <CollapsibleBody
      messageId={user.id}
      sessionId={user.session_id}
      content={user.content}
      highlightQuery={highlightQuery}
    />
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
          class="whitespace-pre-wrap break-all {i > 0 ? 'mt-3' : ''}"
          data-testid="tool-call-row"
          data-tool-call-id={call.id}
          use:contextmenu={{
            target: {
              type: 'tool_call',
              id: call.id,
              sessionId: assistant?.session_id ?? user?.session_id ?? '',
              messageId: call.messageId
            }
          }}><span
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
    class="relative rounded border px-3 py-2 bg-slate-900 group
      {bulkMode && assistant && isSelected(assistant.id)
        ? 'border-emerald-500 bg-emerald-900/10'
        : isStreaming
          ? 'border-amber-900/50'
          : assistant?.pinned
            ? 'border-amber-500/60'
            : 'border-slate-800'}
      {assistant?.hidden_from_context ? 'opacity-50' : ''}"
    data-testid="assistant-article"
    data-message-id={assistant?.id ?? ''}
    data-pinned={assistant?.pinned ? 'true' : 'false'}
    data-hidden-from-context={assistant?.hidden_from_context ? 'true' : 'false'}
    use:contextmenu={{
      target: assistant
        ? {
            type: 'message',
            id: assistant.id,
            sessionId: assistant.session_id,
            role: 'assistant'
          }
        : null
    }}
  >
    <header
      class="flex items-center justify-between text-[10px] uppercase tracking-wider mb-1
        {isStreaming ? 'text-amber-400' : 'text-slate-500'}"
    >
      <span class="flex items-center gap-2">
        {#if bulkMode && assistant}
          <input
            type="checkbox"
            class="accent-emerald-500 cursor-pointer"
            aria-label={`Select assistant message ${assistant.id}`}
            checked={isSelected(assistant.id)}
            onclick={(e) => onCheckboxClick(e, assistant!)}
            data-testid="bulk-checkbox"
            data-message-id={assistant.id}
          />
        {/if}
        <span>assistant{isStreaming ? ' · streaming' : ''}</span>
        {#if assistant?.pinned}
          <span class="text-amber-400 normal-case" title="Pinned">📌</span>
        {/if}
        {#if assistant?.hidden_from_context}
          <span class="text-slate-500 normal-case" title="Hidden from context window"
            >👁‍🗨 hidden</span
          >
        {/if}
      </span>
    </header>
    {#if assistant}
      <CollapsibleBody
        messageId={assistant.id}
        sessionId={assistant.session_id}
        content={assistant.content}
        highlightQuery={highlightQuery}
        disabled={isStreaming}
      />
    {:else}
      <CollapsibleBody
        messageId={null}
        sessionId={user?.session_id ?? null}
        content={streamingContent}
        highlightQuery={highlightQuery}
        disabled={true}
      />
      <span class="inline-block animate-pulse">▍</span>
    {/if}
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
