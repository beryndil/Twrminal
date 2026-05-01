<script lang="ts">
  /**
   * Inspector Context tab — Phase 3 of the v1.0.0 dashboard redesign.
   *
   * The mockup organized the right sidebar's first tab as a stack of
   * narrow cards summarizing the session's "live context": where it
   * runs, what it's tagged with, what memories are loaded, the
   * assembled system prompt, totals, health, and tool calls. This
   * component owns all of that.
   *
   * Stack order (top → bottom):
   *   1. Active Context     — working_dir + model
   *   2. Tags               — session tags
   *   3. Memories           — tag_memory layer count + placeholder
   *   4. System Prompt      — assembled layers (existing UI)
   *   5. Session Metrics    — token totals grid
   *   6. Session Health     — connection + Claude + recovery + auto-save
   *   7. Agent Tool Calls   — running list (existing UI)
   *   8. Session Instructions — inline editor (existing UI)
   *
   * Pre-Phase-3 the Inspector had two `<details>` disclosures
   * (Context + Agent). With tabs replacing the outer disclosure,
   * everything in this tab is always-rendered — the user opened the
   * tab, they want the data; lazy disclosures inside a tab feel like
   * extra clicks for nothing.
   */
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import { stickToBottom } from '$lib/actions/autoscroll';
  import { formatDuration } from '$lib/utils/datetime';
  import * as api from '$lib/api';
  import type { SystemPrompt } from '$lib/api';

  // ---------- shared formatters ---------------------------------------

  function callMarker(ok: boolean | null): { glyph: string; cls: string } {
    if (ok === null) return { glyph: '●', cls: 'text-amber-400' };
    if (ok) return { glyph: '✓', cls: 'text-emerald-400' };
    return { glyph: '✗', cls: 'text-rose-400' };
  }

  function elapsed(startedAt: number, finishedAt: number | null): string {
    if (finishedAt === null) return 'running';
    return formatDuration(finishedAt - startedAt);
  }

  function layerBadgeClasses(kind: string): string {
    switch (kind) {
      case 'base':
        return 'bg-slate-800 text-slate-400';
      case 'session_description':
        return 'bg-indigo-900 text-indigo-300';
      case 'tag_memory':
        return 'bg-teal-900 text-teal-300';
      case 'session':
        return 'bg-amber-900 text-amber-300';
      default:
        return 'bg-slate-800 text-slate-400';
    }
  }

  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
    return String(n);
  }

  // ---------- system prompt -------------------------------------------

  let systemPrompt = $state<SystemPrompt | null>(null);
  let contextLoading = $state(false);
  let contextError = $state<string | null>(null);
  let loadedForSession = $state<string | null>(null);

  async function loadSystemPrompt(sessionId: string): Promise<void> {
    contextLoading = true;
    contextError = null;
    try {
      systemPrompt = await api.getSystemPrompt(sessionId);
      loadedForSession = sessionId;
    } catch (err) {
      contextError = err instanceof Error ? err.message : String(err);
      systemPrompt = null;
    } finally {
      contextLoading = false;
    }
  }

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      systemPrompt = null;
      loadedForSession = null;
      return;
    }
    if (sid !== loadedForSession) void loadSystemPrompt(sid);
  });

  // Re-fetch when session updates land — tag attach/detach or
  // session-instructions edits change layer content underneath.
  $effect(() => {
    void sessions.selected?.updated_at;
    const sid = sessions.selected?.id ?? null;
    if (!sid) return;
    void loadSystemPrompt(sid);
  });

  let memoryLayerCount = $derived(
    systemPrompt?.layers.filter((l) => l.kind === 'tag_memory').length ?? 0
  );

  // ---------- session tags --------------------------------------------

  let sessionTags = $state<api.Tag[]>([]);

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    void sessions.selected?.updated_at;
    if (!sid) {
      sessionTags = [];
      return;
    }
    api.listSessionTags(sid).then(
      (r) => {
        if (sessions.selected?.id === sid) sessionTags = r;
      },
      () => {}
    );
  });

  // ---------- token totals --------------------------------------------

  let tokenTotals = $state<api.TokenTotals | null>(null);
  let prevStreaming = false;

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      tokenTotals = null;
      return;
    }
    api.getSessionTokens(sid).then(
      (r) => {
        if (sessions.selected?.id === sid) tokenTotals = r;
      },
      () => {}
    );
  });

  $effect(() => {
    const active = conversation.streamingActive;
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      prevStreaming = active;
      return;
    }
    if (prevStreaming && !active) {
      api.getSessionTokens(sid).then(
        (r) => {
          if (sessions.selected?.id === sid) tokenTotals = r;
        },
        () => {}
      );
    }
    prevStreaming = active;
  });

  // ---------- session instructions ------------------------------------

  let instructionsDraft = $state('');
  let instructionsSaving = $state(false);
  let instructionsError = $state<string | null>(null);
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

  let instructionsDirty = $derived(
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
    instructionsDraft = updated.session_instructions ?? '';
    instructionsLoadedFor = sel.id;
    void loadSystemPrompt(sel.id);
  }

  function resetInstructions() {
    instructionsDraft = sessions.selected?.session_instructions ?? '';
    instructionsError = null;
  }

  // ---------- agent tool calls ----------------------------------------

  let toolScrollContainer: HTMLElement | undefined = $state();
  let runningCount = $derived(conversation.toolCalls.filter((t) => t.ok === null).length);
  let toolStreamSignal = $derived(
    conversation.toolCalls.reduce(
      (acc, c) => acc + (c.output?.length ?? 0) + (c.error?.length ?? 0),
      conversation.toolCalls.length
    )
  );
</script>

<div class="flex flex-col gap-3 p-4" data-testid="inspector-tab-context-content">
  {#if !sessions.selected}
    <p class="text-sm text-slate-500">Select a session to inspect its context.</p>
  {:else}
    <!-- ===== Active Context ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-active-context"
    >
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
        Active Context
      </h3>
      <dl class="grid grid-cols-[5rem_1fr] gap-y-1 text-xs">
        <dt class="text-slate-500">Directory</dt>
        <dd class="truncate font-mono text-slate-300" title={sessions.selected.working_dir}>
          {sessions.selected.working_dir}
        </dd>
        <dt class="text-slate-500">Model</dt>
        <dd class="truncate font-mono text-slate-300">{sessions.selected.model}</dd>
      </dl>
    </section>

    <!-- ===== Tags ===== -->
    <section class="rounded-md border border-slate-800 bg-slate-950/40 p-3" data-testid="card-tags">
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">Tags</h3>
      {#if sessionTags.length === 0}
        <p class="text-xs text-slate-500">None — attach via the right-click menu.</p>
      {:else}
        <ul class="flex flex-wrap gap-1">
          {#each sessionTags as tag (tag.id)}
            <li
              class="inline-flex items-center gap-1 rounded bg-slate-800 px-1.5 py-0.5
                font-mono text-[10px] text-slate-300"
            >
              {#if tag.pinned}
                <span class="text-amber-400" aria-hidden="true">★</span>
              {/if}
              <span>{tag.name}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <!-- ===== Memories ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-memories"
    >
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">Memories</h3>
      <p class="text-xs text-slate-300">
        {memoryLayerCount} memory layer{memoryLayerCount === 1 ? '' : 's'} loaded
      </p>
      <p class="mt-1 text-[11px] text-slate-500">
        Memory CRUD ships in Phase 4 — backed by the
        <code class="rounded bg-slate-800 px-1 text-accent-brand">tag_memory</code> system-prompt layer.
      </p>
    </section>

    <!-- ===== System Prompt ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-system-prompt"
    >
      <header class="mb-2 flex items-baseline justify-between gap-2">
        <h3 class="text-[10px] font-medium uppercase tracking-wider text-slate-500">
          System Prompt
        </h3>
        {#if systemPrompt}
          <span class="font-mono text-[10px] text-slate-500">~{systemPrompt.total_tokens} tok</span>
        {/if}
      </header>
      {#if contextLoading}
        <p class="text-xs text-slate-500">Loading…</p>
      {:else if contextError}
        <p class="text-xs text-rose-400">Failed: {contextError}</p>
      {:else if systemPrompt}
        <ul class="flex flex-col gap-2">
          {#each systemPrompt.layers as layer, i (`${layer.kind}:${layer.name}:${i}`)}
            <li class="rounded border border-slate-800 bg-slate-950/40 p-2 text-xs">
              <div class="flex items-center justify-between gap-2">
                <span class="truncate font-mono font-medium">{layer.name}</span>
                <span
                  class="{layerBadgeClasses(
                    layer.kind
                  )} rounded px-1.5 py-0.5 text-[10px] uppercase"
                >
                  {layer.kind}
                </span>
              </div>
              <div class="mt-0.5 text-[10px] text-slate-500">~{layer.token_count} tok</div>
              <details class="mt-2">
                <summary class="cursor-pointer text-[11px] text-slate-400">content</summary>
                <pre
                  class="mt-1 whitespace-pre-wrap break-all text-[10px] text-slate-300">{layer.content}</pre>
              </details>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="text-xs text-slate-500">No prompt loaded.</p>
      {/if}
    </section>

    <!-- ===== Session Metrics ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-session-metrics"
    >
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
        Session Metrics
      </h3>
      {#if tokenTotals}
        <dl class="grid grid-cols-2 gap-2 text-xs" data-testid="session-metrics-grid">
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Input</dt>
            <dd class="font-mono text-sm text-slate-200">{fmtTokens(tokenTotals.input_tokens)}</dd>
          </div>
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Output</dt>
            <dd class="font-mono text-sm text-slate-200">{fmtTokens(tokenTotals.output_tokens)}</dd>
          </div>
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Cache read</dt>
            <dd class="font-mono text-sm text-emerald-300">
              {fmtTokens(tokenTotals.cache_read_tokens)}
            </dd>
          </div>
          <div class="rounded bg-slate-900 px-2 py-1.5">
            <dt class="text-[10px] uppercase tracking-wider text-slate-500">Cache write</dt>
            <dd class="font-mono text-sm text-slate-200">
              {fmtTokens(tokenTotals.cache_creation_tokens)}
            </dd>
          </div>
        </dl>
      {:else}
        <p class="text-xs text-slate-500">No tokens billed yet.</p>
      {/if}
    </section>

    <!-- ===== Session Health (UI-only aggregator) ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-session-health"
    >
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
        Session Health
      </h3>
      <div class="flex items-center gap-2">
        <span
          class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full
            {agent.state === 'open'
            ? 'bg-accent-brand-soft/60 text-accent-brand'
            : 'bg-slate-800 text-slate-500'}"
          aria-hidden="true">♥</span
        >
        <div class="min-w-0">
          <div class="text-xs font-medium text-slate-200">
            {agent.state === 'open'
              ? 'Healthy'
              : agent.state === 'connecting'
                ? 'Connecting'
                : 'Disconnected'}
          </div>
          <div class="text-[11px] text-slate-500">
            {agent.state === 'open' ? 'All systems normal' : 'Reconnecting will resume the stream'}
          </div>
        </div>
      </div>
      <ul class="mt-2 flex flex-col gap-0.5 text-[11px]">
        <li class="flex items-center gap-2 text-slate-400">
          <span
            class="h-1.5 w-1.5 rounded-full
              {agent.state === 'open' ? 'bg-accent-brand' : 'bg-slate-600'}"
            aria-hidden="true"
          ></span>
          Claude {agent.state === 'open' ? 'connected' : 'unreachable'}
        </li>
        <li class="flex items-center gap-2 text-slate-400">
          <span class="h-1.5 w-1.5 rounded-full bg-accent-brand" aria-hidden="true"></span>
          Recovery armed
        </li>
        <li class="flex items-center gap-2 text-slate-400">
          <span class="h-1.5 w-1.5 rounded-full bg-accent-brand" aria-hidden="true"></span>
          Auto-save active
        </li>
      </ul>
    </section>

    <!-- ===== Agent Tool Calls ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-agent-tool-calls"
    >
      <header class="mb-2 flex items-baseline justify-between gap-2">
        <h3 class="text-[10px] font-medium uppercase tracking-wider text-slate-500">
          Agent Tool Calls
        </h3>
        <span class="text-[11px] text-slate-500">
          {conversation.toolCalls.length}
          {#if runningCount > 0}
            <span
              class="ml-1 rounded bg-amber-900 px-1.5 py-0.5 text-[9px] uppercase text-amber-300"
            >
              {runningCount} running
            </span>
          {/if}
        </span>
      </header>
      {#if conversation.toolCalls.length === 0}
        <p class="text-xs text-slate-500">No tool calls yet.</p>
      {:else}
        <div
          bind:this={toolScrollContainer}
          use:stickToBottom={toolStreamSignal}
          class="max-h-[28rem] overflow-y-auto rounded border border-slate-800 bg-black/70 p-2
            font-mono text-[10px] leading-relaxed text-slate-300"
        >
          {#each conversation.toolCalls as call, i (call.id)}
            {@const mark = callMarker(call.ok)}
            <pre class="whitespace-pre-wrap break-all {i > 0 ? 'mt-3' : ''}"><span
                class="text-emerald-400">$ {call.name}</span
              > <span class={mark.cls}>{mark.glyph}</span> <span class="text-slate-500"
                >{elapsed(call.startedAt, call.finishedAt)}</span
              >{#if call.outputTruncated}
                <span class="text-amber-400">[truncated]</span>{/if}
{JSON.stringify(call.input, null, 2)}{#if call.output !== null}
                {call.output}{/if}{#if call.error}
                <span class="text-rose-400">error: {call.error}</span>{/if}</pre>
          {/each}
        </div>
      {/if}
    </section>

    <!-- ===== Session Instructions ===== -->
    <section
      class="rounded-md border border-slate-800 bg-slate-950/40 p-3"
      data-testid="card-session-instructions"
    >
      <header class="mb-2 flex items-baseline justify-between gap-2">
        <h3 class="text-[10px] font-medium uppercase tracking-wider text-slate-500">
          Session Instructions
        </h3>
        <span class="text-[10px] text-slate-600">last layer — always wins</span>
      </header>
      <textarea
        class="min-h-[4rem] w-full resize-y rounded border border-slate-800 bg-slate-950 px-2
          py-2 text-xs focus:border-slate-600 focus:outline-none"
        rows="4"
        placeholder="One-off instructions for this session…"
        bind:value={instructionsDraft}
      ></textarea>
      {#if instructionsError}
        <p class="mt-1 text-[11px] text-rose-400">{instructionsError}</p>
      {/if}
      <div class="mt-1 flex items-center justify-end gap-1.5">
        {#if instructionsDirty}
          <button
            type="button"
            class="rounded bg-slate-800 px-2 py-1 text-[11px] hover:bg-slate-700"
            onclick={resetInstructions}
            disabled={instructionsSaving}
          >
            Reset
          </button>
        {/if}
        <button
          type="button"
          class="rounded bg-accent-brand px-2 py-1 text-[11px] hover:bg-accent-brand/90
            disabled:opacity-50"
          onclick={saveInstructions}
          disabled={!instructionsDirty || instructionsSaving}
        >
          {instructionsSaving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </section>
  {/if}
</div>
