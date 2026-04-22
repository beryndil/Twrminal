<script lang="ts">
  /**
   * Compact chat panel rendered above the checklist body in
   * ChecklistView (v0.5.2). Lets the user converse with the agent
   * about the whole list without spawning a per-item paired chat.
   *
   * Scope: intentionally minimal. We show user/assistant text, the
   * streaming delta, and a textarea with a send button. No tool-call
   * rendering, no permission-mode picker, no approval modal — if the
   * user needs that level of UX they can open a full Conversation
   * pane on a chat session instead. The backend's
   * `checklist_overview` prompt layer injects list context into every
   * turn, so the agent's responses are grounded in the checklist
   * without any frontend plumbing.
   *
   * The component owns the agent connection lifecycle for the
   * checklist session: connect on mount + when the session changes,
   * disconnect on unmount. This mirrors how Conversation.svelte
   * relates to chat sessions, adapted to the embedded context.
   */

  import { onDestroy } from 'svelte';
  import { agent } from '$lib/agent.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';

  const selected = $derived(sessions.selected);

  // Connect / reconnect whenever the selected checklist session
  // changes. Guarded on `kind === 'checklist'` so a race where the
  // user switches to a chat session before the effect teardown runs
  // doesn't double-connect (ChecklistView unmounts in that case
  // anyway, but belt-and-braces).
  $effect(() => {
    const sid = selected?.id ?? null;
    if (!sid || selected?.kind !== 'checklist') return;
    // Skip if we're already pointing at this session (open OR in
    // flight). `agent.connect()` closes + reopens, so re-firing
    // during 'connecting' would tear down the fresh socket and
    // paint a bogus error flash.
    if (
      agent.sessionId === sid &&
      (agent.state === 'open' || agent.state === 'connecting')
    ) {
      return;
    }
    void agent.connect(sid);
  });

  onDestroy(() => {
    agent.close();
  });

  // Pull the raw message list + streaming state from the conversation
  // store. We deliberately don't use `buildTurns` — that logic exists
  // to group tool calls into user/assistant turn pairs, which we're
  // not rendering. Chronological user/assistant text is enough.
  const messages = $derived(conversation.messages);
  const streamingActive = $derived(conversation.streamingActive);
  const streamingText = $derived(conversation.streamingText);
  const streamingMessageId = $derived(conversation.streamingMessageId);

  let draft = $state('');
  let textarea: HTMLTextAreaElement | undefined = $state();
  let scroller: HTMLDivElement | undefined = $state();

  // Auto-scroll to the newest message whenever messages change or the
  // streaming delta advances. Keeps the latest assistant text visible
  // without the user having to scroll inside the compact panel.
  $effect(() => {
    // Touch the reactive deps so the effect re-runs on every update.
    void messages.length;
    void streamingText;
    if (scroller) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  });

  function canSend(): boolean {
    return (
      draft.trim() !== '' &&
      agent.state === 'open' &&
      selected?.kind === 'checklist' &&
      !selected.closed_at
    );
  }

  function send() {
    if (!canSend()) return;
    const text = draft.trim();
    const ok = agent.send(text);
    if (ok) {
      draft = '';
      textarea?.focus();
    }
  }

  function onKey(ev: KeyboardEvent) {
    // Enter sends, Shift+Enter inserts a newline. Mirrors the main
    // Conversation composer's contract so muscle memory carries over.
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      send();
    }
  }

  function stop() {
    agent.stop();
  }

  // Assistant-side streaming placeholder. We display the streaming
  // delta under the last assistant message bubble when the store
  // signals a turn is in flight and the streaming id isn't already a
  // finalised row. The store's own dedupe handles the hand-off; this
  // is purely visual.
  const showStreaming = $derived(
    streamingActive &&
      (streamingMessageId === null ||
        !messages.some((m) => m.id === streamingMessageId))
  );
</script>

<section
  class="flex min-h-0 flex-col border-b border-slate-800 bg-slate-950"
  data-testid="checklist-chat"
>
  <header class="flex items-center gap-2 border-b border-slate-900 px-4 py-1 text-xs text-slate-500">
    <span aria-hidden="true">💬</span>
    <span>Chat about this list</span>
    {#if agent.state !== 'open' && agent.state !== 'idle'}
      <span class="ml-auto text-slate-600">{agent.state}</span>
    {/if}
  </header>

  <div
    bind:this={scroller}
    class="flex max-h-64 min-h-16 flex-col gap-2 overflow-y-auto px-4 py-2 text-sm"
    data-testid="checklist-chat-messages"
  >
    {#if messages.length === 0 && !showStreaming}
      <p class="text-xs text-slate-500">
        Ask Claude about this checklist. The list's current state is
        injected into every turn.
      </p>
    {/if}
    {#each messages as msg (msg.id)}
      {#if msg.role === 'user'}
        <div
          class="self-end max-w-[85%] rounded bg-sky-900/40 px-2 py-1 text-slate-100"
          data-testid="checklist-chat-user"
        >
          <p class="whitespace-pre-wrap break-words">{msg.content}</p>
        </div>
      {:else if msg.role === 'assistant'}
        <div
          class="self-start max-w-[90%] rounded bg-slate-900 px-2 py-1 text-slate-100"
          data-testid="checklist-chat-assistant"
        >
          <p class="whitespace-pre-wrap break-words">{msg.content}</p>
        </div>
      {/if}
    {/each}
    {#if showStreaming}
      <div
        class="self-start max-w-[90%] rounded bg-slate-900 px-2 py-1 text-slate-300"
        data-testid="checklist-chat-streaming"
      >
        <p class="whitespace-pre-wrap break-words">
          {streamingText}<span class="ml-0.5 animate-pulse text-slate-500">▍</span>
        </p>
      </div>
    {/if}
  </div>

  <form
    class="flex items-start gap-2 border-t border-slate-900 px-4 py-2"
    onsubmit={(ev) => {
      ev.preventDefault();
      send();
    }}
  >
    <textarea
      bind:this={textarea}
      bind:value={draft}
      onkeydown={onKey}
      class="flex-1 resize-y rounded border border-slate-800 bg-slate-900 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
      rows="2"
      placeholder={selected?.closed_at
        ? 'Checklist is closed — reopen to chat'
        : 'Ask about this list…'}
      aria-label="Chat message"
      disabled={!!selected?.closed_at}
      data-testid="checklist-chat-input"
    ></textarea>
    {#if streamingActive}
      <button
        type="button"
        class="self-stretch rounded bg-rose-700 px-3 text-xs font-medium text-white hover:bg-rose-600"
        onclick={stop}
        data-testid="checklist-chat-stop"
      >
        Stop
      </button>
    {:else}
      <button
        type="submit"
        class="self-stretch rounded bg-sky-600 px-3 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        disabled={!canSend()}
        data-testid="checklist-chat-send"
      >
        Send
      </button>
    {/if}
  </form>
</section>
