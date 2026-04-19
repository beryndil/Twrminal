<script lang="ts">
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import { renderMarkdown } from '$lib/render';

  let promptText = $state('');
  let scrollContainer: HTMLDivElement | undefined = $state();

  $effect(() => {
    void conversation.messages;
    void conversation.streamingText;
    if (scrollContainer) {
      queueMicrotask(() => {
        if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
      });
    }
  });

  function onSend() {
    const text = promptText.trim();
    if (!text) return;
    if (!agent.send(text)) return;
    promptText = '';
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSend();
    }
  }

  function connectionLabel(state: typeof agent.state): string {
    if (agent.reconnectDelayMs !== null) {
      return `retrying in ${Math.ceil(agent.reconnectDelayMs / 1000)}s`;
    }
    switch (state) {
      case 'idle':
        return 'idle';
      case 'connecting':
        return 'connecting…';
      case 'open':
        return 'connected';
      case 'closed':
        return agent.lastCloseCode === 4404 ? 'session not found' : 'disconnected';
      case 'error':
        return 'error';
    }
  }
</script>

<section class="bg-slate-900 overflow-hidden flex flex-col min-w-0">
  <header class="border-b border-slate-800 px-4 py-3 flex items-baseline justify-between">
    <div class="min-w-0">
      <h1 class="text-lg font-medium">
        {sessions.selected?.title ?? 'Twrminal'}
      </h1>
      <p class="text-xs text-slate-500 font-mono truncate">
        {sessions.selected
          ? `${sessions.selected.model} · ${sessions.selected.working_dir}`
          : 'select or create a session to start'}
      </p>
    </div>
    <span
      class="text-[10px] uppercase tracking-wider px-2 py-1 rounded
        {agent.state === 'open'
          ? 'bg-emerald-900 text-emerald-300'
          : agent.state === 'connecting'
            ? 'bg-amber-900 text-amber-300'
            : 'bg-slate-800 text-slate-400'}"
    >
      {connectionLabel(agent.state)}
    </span>
  </header>

  <div bind:this={scrollContainer} class="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
    {#if !sessions.selectedId}
      <p class="text-slate-500 text-sm">No session selected.</p>
    {:else if conversation.messages.length === 0 && !conversation.streamingActive}
      <p class="text-slate-500 text-sm">
        No messages yet. Send a prompt to start the conversation.
      </p>
    {:else}
      {#each conversation.messages as msg (msg.id)}
        <article
          class="rounded border border-slate-800 px-3 py-2
          {msg.role === 'user' ? 'bg-slate-800/60' : 'bg-slate-900'}"
        >
          <header class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
            {msg.role}
          </header>
          <div class="prose prose-invert prose-sm max-w-none">
            {@html renderMarkdown(msg.content)}
          </div>
        </article>
      {/each}

      {#if conversation.streamingActive}
        <article class="rounded border border-amber-900/50 px-3 py-2 bg-slate-900">
          <header class="text-[10px] uppercase tracking-wider text-amber-400 mb-1">
            assistant · streaming
          </header>
          <div class="prose prose-invert prose-sm max-w-none">
            {@html renderMarkdown(conversation.streamingText)}
            <span class="inline-block animate-pulse">▍</span>
          </div>
        </article>
      {/if}

      {#if conversation.error}
        <article class="rounded border border-rose-900/50 px-3 py-2 bg-rose-950/30">
          <header class="text-[10px] uppercase tracking-wider text-rose-400 mb-1">
            error
          </header>
          <pre class="text-xs text-rose-300 whitespace-pre-wrap">{conversation.error}</pre>
        </article>
      {/if}
    {/if}
  </div>

  <form
    class="border-t border-slate-800 px-4 py-3 flex gap-2 items-end"
    onsubmit={(e) => {
      e.preventDefault();
      onSend();
    }}
  >
    <textarea
      class="flex-1 rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm
        resize-none focus:outline-none focus:border-slate-600 disabled:opacity-50"
      rows="2"
      placeholder={sessions.selectedId
        ? 'Send a prompt (⌘/Ctrl+Enter)'
        : 'Select a session first'}
      bind:value={promptText}
      onkeydown={onKeydown}
      disabled={!sessions.selectedId || agent.state !== 'open'}
    ></textarea>
    <button
      type="submit"
      class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm
        disabled:opacity-50 disabled:cursor-not-allowed"
      disabled={!sessions.selectedId || agent.state !== 'open' || !promptText.trim()}
    >
      Send
    </button>
  </form>
</section>
