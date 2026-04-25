<script lang="ts">
  import type { Message } from '$lib/api';
  import type { LiveToolCall } from '$lib/stores/conversation.svelte';
  import { stickToBottom } from '$lib/actions/autoscroll';
  import { contextmenu } from '$lib/actions/contextmenu';
  import { contextmenuDelegate } from '$lib/actions/contextmenu-delegate';
  import { linkify } from '$lib/linkify';
  import { preferences } from '$lib/stores/preferences.svelte';
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
    /** "More info" elaborate-on-this-reply button. Only rendered on
     * the most-recent finished assistant turn (see `isLatestAssistant`)
     * to keep the contract clear: clicking pre-fills the composer with
     * an "elaborate on your previous response" prompt — and there's
     * exactly one "previous response" the model is going to read,
     * which is the latest one. Pre-fill + focus, never auto-send;
     * Dave can edit or Esc-cancel before pressing Enter. */
    onMoreInfo?: (msg: Message) => void;
    isLatestAssistant?: boolean;
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
    /** Session working directory. Plumbed through so the tool-output
     * linkifier can resolve relative paths (e.g. `frontend/src/lib/foo.ts`
     * in a Read result) into absolute `file://` URLs the existing
     * "Open in editor" link handler can dispatch. Null when the host
     * session isn't selected yet — relative paths then stay plain text.
     * Absolute paths and bare URLs work regardless. */
    workingDir?: string | null;
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
    onMoreInfo,
    isLatestAssistant = false,
    bulkMode = false,
    selectedIds,
    onToggleSelect,
    workingDir = null
  }: Props = $props();

  /** Render a tool-call payload (input JSON, output, error) with URLs
   * and file paths converted to anchors. Wraps the existing
   * `linkify` helper into a per-call closure so the template stays
   * readable. */
  function linkifiedSegment(text: string | null | undefined): string {
    return linkify(text ?? '', workingDir);
  }

  const runningCount = $derived(toolCalls.filter((t) => t.ok === null).length);
  // First still-running sub-agent call, if any. Its description is
  // surfaced into the summary row so users who leave the tool-work
  // `<details>` collapsed still see *what* the long-running
  // `Agent`/`Task` call is doing during an 80s+ wait (see TODO.md
  // silence-gap entry). Function-declaration hoisting makes
  // `isSubAgent` safe to reference here despite appearing below.
  const firstRunningSubAgent = $derived(
    toolCalls.find((t) => t.finishedAt === null && isSubAgent(t.name)) ?? null
  );
  const thinkingCombined = $derived(thinking + streamingThinking);

  // Aggregate signal for the stick-to-bottom action: grows whenever a
  // new call appears or any existing call's output/error lengthens.
  const toolStreamSignal = $derived(
    toolCalls.reduce(
      (acc, c) => acc + (c.output?.length ?? 0) + (c.error?.length ?? 0),
      toolCalls.length
    )
  );

  // Wall-clock "now" for the live-elapsed readout on running tool
  // calls. Ticks once a second only while at least one call in this
  // turn is still running — idle turns pay nothing. The effect tears
  // its timer down when the last running call finishes so completed
  // turns don't keep firing timers forever. Separate from the P1
  // backend `tool_progress` keepalive: this is the local render
  // clock that paints the elapsed number; the backend event keeps
  // the wire warm and nudges the reactive graph when the tab is
  // backgrounded (see P2 in TODO.md silence-gap entry).
  let now = $state(Date.now());
  $effect(() => {
    const hasRunning = toolCalls.some((t) => t.finishedAt === null);
    if (!hasRunning) return;
    const id = setInterval(() => {
      now = Date.now();
    }, 1000);
    return () => clearInterval(id);
  });

  function formatElapsed(
    startedAt: number,
    nowMs: number,
    lastProgressMs: number | null
  ): string {
    // Take the max of (local wall-clock delta) and (server-reported
    // monotonic). Foreground tabs use the local clock almost
    // exclusively — it ticks every 1s via the effect above. A
    // backgrounded tab whose `setInterval` got throttled has a stale
    // `nowMs`; the server's monotonic number from `tool_progress`
    // keepalives prevents the readout from freezing. See reducer
    // `tool_progress` case and TODO.md silence-gap entry.
    const localMs = Math.max(0, nowMs - startedAt);
    const effectiveMs = Math.max(localMs, lastProgressMs ?? 0);
    const s = Math.floor(effectiveMs / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}m${rem.toString().padStart(2, '0')}s`;
  }

  function callMarker(ok: boolean | null): { glyph: string; cls: string } {
    if (ok === null) return { glyph: '●', cls: 'text-amber-400' };
    if (ok) return { glyph: '✓', cls: 'text-emerald-400' };
    return { glyph: '✗', cls: 'text-rose-400' };
  }

  /** Tools that spawn an out-of-band sub-agent. The SDK emits nothing
   * between the outer-turn `tool_use` and the eventual `tool_result`
   * (see TODO.md silence-gap entry), so the UI carries the full
   * liveness burden during the wait. `Agent` is Claude Code's name
   * for the sub-agent tool; `Task` is the legacy alias that still
   * shows up in older transcripts. Matched on the wire `name` so
   * stragglers from either generation light up correctly. */
  function isSubAgent(name: string): boolean {
    return name === 'Agent' || name === 'Task';
  }

  function subAgentSubtitle(input: Record<string, unknown>): string {
    const desc = input['description'];
    if (typeof desc === 'string' && desc.length > 0) return desc;
    return 'running…';
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
        <span>{preferences.displayName ?? 'user'}</span>
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
  <!-- Open state is purely user-controlled. The summary row already
       carries liveness (count + pulsing "N running" badge), so we no
       longer force-open when tools start — that produced an
       expand/collapse flash on every tool call. User clicks to peek;
       state changes leave `open` alone. -->
  <details
    class="ml-6 rounded bg-slate-950/40 border border-slate-800/60 px-2 py-1"
  >
    <summary
      class="cursor-pointer text-[10px] uppercase tracking-wider text-slate-500
        flex items-center gap-2"
    >
      <span>tool work · {toolCalls.length}</span>
      {#if runningCount > 0}
        <span
          class="bg-amber-900 text-amber-300 px-1.5 py-0.5 rounded text-[9px] uppercase
            animate-pulse flex items-center gap-1"
          data-testid="tool-work-running-badge"
        >
          <span aria-hidden="true">●</span>
          {runningCount} running
        </span>
      {/if}
      {#if firstRunningSubAgent}
        <span
          class="normal-case tracking-normal text-amber-200 truncate max-w-sm min-w-0"
          data-testid="tool-work-subagent-subtitle"
          title={subAgentSubtitle(firstRunningSubAgent.input)}
        >
          — {subAgentSubtitle(firstRunningSubAgent.input)}
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
        {@const running = call.finishedAt === null}
        <pre
          class="whitespace-pre-wrap break-all {i > 0 ? 'mt-3' : ''}"
          data-testid="tool-call-row"
          data-tool-call-id={call.id}
          data-running={running ? 'true' : 'false'}
          use:contextmenuDelegate={{
            sessionId: assistant?.session_id ?? user?.session_id ?? null,
            messageId: call.messageId
          }}
          use:contextmenu={{
            target: {
              type: 'tool_call',
              id: call.id,
              sessionId: assistant?.session_id ?? user?.session_id ?? '',
              messageId: call.messageId
            }
          }}><span
            class="text-emerald-400">$ {call.name}</span> <span
            class={mark.cls}>{mark.glyph}</span>{#if running} <span
            class="inline-block animate-pulse text-amber-400"
            data-testid="tool-call-pulse"
            aria-hidden="true">●</span> <span
            class="text-amber-300"
            data-testid="tool-call-elapsed">{formatElapsed(call.startedAt, now, call.lastProgressMs)}</span>{#if isSubAgent(call.name)} <span
            class="text-amber-200"
            data-testid="tool-call-subagent">— running sub-agent: {subAgentSubtitle(call.input)}</span>{/if}{/if}{#if call.outputTruncated} <span
            class="text-amber-400">[truncated]</span>{/if}
{@html linkifiedSegment(JSON.stringify(call.input, null, 2))}{#if call.output !== null}
{@html linkifiedSegment(call.output)}{/if}{#if call.error}
<span class="text-rose-400">error: {@html linkifiedSegment(call.error)}</span>{/if}</pre>
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
      <div class="mt-2 flex justify-end gap-3">
        {#if isLatestAssistant && !isStreaming && onMoreInfo}
          <button
            type="button"
            class="text-[10px] uppercase tracking-wider text-slate-500 hover:text-slate-300"
            aria-label="Ask for more detail on this reply"
            title="Pre-fill composer to ask for more detail (Enter to send)"
            data-testid="more-info-button"
            onclick={() => onMoreInfo(assistant!)}
          >
            ℹ more
          </button>
        {/if}
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
