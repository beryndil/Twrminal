<script lang="ts">
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { getSystemPrompt, type SystemPrompt } from '$lib/api';
  import { stickToBottom } from '$lib/actions/autoscroll';

  function callMarker(ok: boolean | null): { glyph: string; cls: string } {
    if (ok === null) return { glyph: '●', cls: 'text-amber-400' };
    if (ok) return { glyph: '✓', cls: 'text-emerald-400' };
    return { glyph: '✗', cls: 'text-rose-400' };
  }

  function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function elapsed(startedAt: number, finishedAt: number | null): string {
    if (finishedAt === null) return 'running';
    return formatDuration(finishedAt - startedAt);
  }

  function layerBadgeClasses(kind: string): string {
    switch (kind) {
      case 'base':
        return 'bg-slate-800 text-slate-400';
      case 'tag_memory':
        return 'bg-teal-900 text-teal-300';
      case 'session':
        return 'bg-amber-900 text-amber-300';
      default:
        return 'bg-slate-800 text-slate-400';
    }
  }

  let agentOpen = $state(true);
  let contextOpen = $state(false);
  let scrollContainer: HTMLElement | undefined = $state();
  const running = $derived(
    conversation.toolCalls.filter((t) => t.ok === null).length
  );
  // Aggregate signal so stickToBottom re-evaluates whenever a new call
  // arrives or any call's output/error grows.
  const toolStreamSignal = $derived(
    conversation.toolCalls.reduce(
      (acc, c) => acc + (c.output?.length ?? 0) + (c.error?.length ?? 0),
      conversation.toolCalls.length
    )
  );

  let systemPrompt = $state<SystemPrompt | null>(null);
  let contextLoading = $state(false);
  let contextError = $state<string | null>(null);
  let loadedForSession = $state<string | null>(null);

  async function loadSystemPrompt(sessionId: string): Promise<void> {
    contextLoading = true;
    contextError = null;
    try {
      systemPrompt = await getSystemPrompt(sessionId);
      loadedForSession = sessionId;
    } catch (err) {
      contextError = err instanceof Error ? err.message : String(err);
      systemPrompt = null;
    } finally {
      contextLoading = false;
    }
  }

  // Refetch when the Context pane is opened or the active session changes
  // while it's open. The assembled prompt is cheap to compute, and the
  // user explicitly opened the pane to see current state.
  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!contextOpen || !sid) return;
    if (sid !== loadedForSession) {
      void loadSystemPrompt(sid);
    }
  });

  // Invalidate when the session list refresh cycle may have changed
  // tag/instructions underneath. Cheapest to just force a reload on
  // the next open. Also re-fetches immediately if the pane is open.
  $effect(() => {
    void sessions.selected?.updated_at;
    loadedForSession = null;
    const sid = sessions.selected?.id ?? null;
    if (contextOpen && sid) void loadSystemPrompt(sid);
  });

  // --- Session instructions inline editor (v0.2.12) ------------------

  let instructionsDraft = $state('');
  let instructionsSaving = $state(false);
  let instructionsError = $state<string | null>(null);
  /** Session id the draft was last hydrated for. Prevents the effect
   * from clobbering in-flight edits on every `sessions.refresh()`. */
  let instructionsLoadedFor = $state<string | null>(null);

  $effect(() => {
    const sel = sessions.selected;
    if (!sel) {
      instructionsLoadedFor = null;
      instructionsDraft = '';
      return;
    }
    if (instructionsLoadedFor === sel.id) return;
    instructionsLoadedFor = sel.id;
    instructionsDraft = sel.session_instructions ?? '';
    instructionsError = null;
  });

  const instructionsDirty = $derived(
    instructionsDraft !== (sessions.selected?.session_instructions ?? '')
  );

  async function saveInstructions() {
    const sel = sessions.selected;
    if (!sel) return;
    instructionsSaving = true;
    instructionsError = null;
    const trimmed = instructionsDraft.trim();
    const updated = await sessions.update(sel.id, {
      session_instructions: trimmed === '' ? null : trimmed,
    });
    instructionsSaving = false;
    if (updated === null) {
      instructionsError = sessions.error;
      return;
    }
    // Sync draft to what the server returned (trimmed form).
    instructionsDraft = updated.session_instructions ?? '';
    instructionsLoadedFor = sel.id;
    // Re-fetch system_prompt if pane is open so the `session` layer
    // reflects the new value immediately.
    if (contextOpen) void loadSystemPrompt(sel.id);
  }

  function resetInstructions() {
    instructionsDraft = sessions.selected?.session_instructions ?? '';
    instructionsError = null;
  }

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
  class="h-full bg-slate-900 overflow-y-auto border-l border-slate-800 p-4 flex flex-col gap-3"
>
  <details class="disclosure-group" bind:open={contextOpen}>
    <summary class="flex items-baseline justify-between gap-2 cursor-pointer">
      <span class="text-sm uppercase tracking-wider text-slate-400">Context</span>
      {#if systemPrompt}
        <span class="text-[10px] text-slate-500 font-mono">
          ~{systemPrompt.total_tokens} tok
        </span>
      {/if}
    </summary>

    {#if !sessions.selected}
      <p class="text-slate-500 text-sm mt-3">Select a session to inspect its system prompt.</p>
    {:else if contextLoading}
      <p class="text-slate-500 text-sm mt-3">Loading…</p>
    {:else if contextError}
      <p class="text-rose-400 text-sm mt-3">Failed: {contextError}</p>
    {:else if systemPrompt}
      <ul class="flex flex-col gap-2 mt-3">
        {#each systemPrompt.layers as layer, i (`${layer.kind}:${layer.name}:${i}`)}
          <li class="rounded border border-slate-800 bg-slate-950/40 p-2 text-xs">
            <div class="flex items-center justify-between gap-2">
              <span class="font-mono font-medium truncate">{layer.name}</span>
              <span class="{layerBadgeClasses(layer.kind)} px-1.5 py-0.5 rounded text-[10px] uppercase">
                {layer.kind}
              </span>
            </div>
            <div class="text-[10px] text-slate-500 mt-0.5">~{layer.token_count} tok</div>
            <details class="mt-2">
              <summary class="cursor-pointer text-slate-400 text-[11px]">content</summary>
              <pre class="mt-1 text-[10px] text-slate-300 whitespace-pre-wrap break-all">{layer.content}</pre>
            </details>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-slate-500 text-sm mt-3">Open to load.</p>
    {/if}

    {#if sessions.selected}
      <section class="mt-4 flex flex-col gap-1.5">
        <div class="flex items-baseline justify-between gap-2">
          <span class="text-[11px] uppercase tracking-wider text-slate-400">
            Session instructions
          </span>
          <span class="text-[10px] text-slate-600">last layer — always wins</span>
        </div>
        <textarea
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-xs
            focus:outline-none focus:border-slate-600 resize-y min-h-[4rem]"
          rows="4"
          placeholder="One-off instructions for this session…"
          bind:value={instructionsDraft}
        ></textarea>
        {#if instructionsError}
          <p class="text-rose-400 text-[11px]">{instructionsError}</p>
        {/if}
        <div class="flex items-center justify-end gap-1.5">
          {#if instructionsDirty}
            <button
              type="button"
              class="text-[11px] rounded bg-slate-800 hover:bg-slate-700 px-2 py-1"
              onclick={resetInstructions}
              disabled={instructionsSaving}
            >
              Reset
            </button>
          {/if}
          <button
            type="button"
            class="text-[11px] rounded bg-emerald-600 hover:bg-emerald-500 px-2 py-1
              disabled:opacity-50"
            onclick={saveInstructions}
            disabled={!instructionsDirty || instructionsSaving}
          >
            {instructionsSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </section>
    {/if}
  </details>

  <details class="disclosure-group" bind:open={agentOpen}>
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
      <div
        use:stickToBottom={toolStreamSignal}
        class="mt-3 max-h-[32rem] overflow-y-auto rounded border border-slate-800
          bg-black/70 p-2 font-mono text-[10px] leading-relaxed text-slate-300"
      >
        {#each conversation.toolCalls as call, i (call.id)}
          {@const mark = callMarker(call.ok)}
          <pre
            class="whitespace-pre-wrap break-all {i > 0 ? 'mt-3' : ''}"><span
              class="text-emerald-400">$ {call.name}</span> <span
              class={mark.cls}>{mark.glyph}</span> <span
              class="text-slate-500">{elapsed(call.startedAt, call.finishedAt)}</span>{#if call.outputTruncated} <span
              class="text-amber-400">[truncated]</span>{/if}
{JSON.stringify(call.input, null, 2)}{#if call.output !== null}
{call.output}{/if}{#if call.error}
<span class="text-rose-400">error: {call.error}</span>{/if}</pre>
        {/each}
      </div>
    {/if}
  </details>
</aside>

<style>
  /* Hide the default details arrow; we carry the disclosure affordance
   * in the summary layout itself. */
  .disclosure-group > summary {
    list-style: none;
  }
  .disclosure-group > summary::-webkit-details-marker {
    display: none;
  }
  /* Small chevron glyph on the summary so the collapse is discoverable. */
  .disclosure-group > summary::before {
    content: '▾';
    color: rgb(100 116 139);
    font-size: 0.75rem;
    margin-right: 0.4rem;
  }
  .disclosure-group:not([open]) > summary::before {
    content: '▸';
  }
</style>
