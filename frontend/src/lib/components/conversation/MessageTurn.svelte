<script lang="ts">
  /**
   * One user/assistant turn — user bubble, optional tool-work
   * drawer, assistant bubble, routing badge, error block.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"What a message turn looks like" —
   *   the per-row anatomy: user bubble, tool drawer, assistant
   *   bubble, routing badge.
   * - ``docs/behavior/chat.md`` §"Conversation rendering" — markdown
   *   bodies render via CommonMark + GFM; the rendered HTML flows
   *   through :func:`sanitizeHtml` before insertion.
   * - ``docs/behavior/tool-output-streaming.md`` §"When output
   *   begins streaming" — the drawer above the assistant bubble
   *   expands per row.
   * - ``docs/behavior/chat.md`` §"Error states" — assistant bubble
   *   closes with a red error block when the agent emits an
   *   error event mid-turn.
   *
   * The component is presentational: receives a ``MessageTurnView``
   * and renders it. The reducer produces these views; the parent
   * Conversation component iterates the list.
   */
  import { CONVERSATION_STRINGS } from "../../config";
  import { linkifyToHtml } from "../../linkify";
  import { renderMarkdown } from "../../render";
  import { sanitizeHtml } from "../../sanitize";
  import type { MessageTurnView } from "../../stores/conversation.svelte";
  import RoutingBadge from "./RoutingBadge.svelte";
  import ToolOutput from "./ToolOutput.svelte";

  interface Props {
    turn: MessageTurnView;
  }

  const { turn }: Props = $props();

  // Body rendering pipeline — marked → DOMPurify. The pipeline runs
  // asynchronously because :func:`renderMarkdown` returns a promise;
  // we cache the resolved HTML on the turn view via a derived
  // ``$state`` so a re-render of the same body doesn't re-parse.
  let bodyHtml = $state<string>("");

  $effect(() => {
    const body = turn.body;
    if (body.length === 0) {
      bodyHtml = "";
      return;
    }
    let cancelled = false;
    void (async () => {
      const html = await renderMarkdown(body);
      if (cancelled) return;
      bodyHtml = sanitizeHtml(html);
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

<article
  class="message-turn flex flex-col gap-2 px-4 py-4"
  data-testid="message-turn"
  data-turn-id={turn.id}
  data-role={turn.role}
>
  {#if turn.role === "user"}
    <div
      class="user-bubble self-end rounded px-3 py-2 text-sm text-fg-strong"
      data-testid="message-turn-user-body"
    >
      <!-- User bubbles get linkifier-anchored URLs / paths but no
           Markdown reflow (chat.md notes user bubbles render as
           Markdown — applying the same renderMarkdown pipeline as
           assistant bubbles is a TODO once the linkifier integrates
           with the marked tokeniser). The HTML output of
           ``linkifyToHtml`` is escaped per-segment; we still pass it
           through ``sanitizeHtml`` for defense in depth. -->
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html sanitizeHtml(linkifyToHtml(turn.body))}
    </div>
  {:else}
    {#if turn.toolCalls.length > 0}
      <details class="rounded border border-border" data-testid="tool-work-drawer" open>
        <summary class="cursor-pointer px-2 py-1 text-xs text-fg-muted">
          {CONVERSATION_STRINGS.toolDrawerLabel} ({turn.toolCalls.length})
        </summary>
        <div class="px-2 py-1">
          {#each turn.toolCalls as call (call.id)}
            <ToolOutput {call} />
          {/each}
        </div>
      </details>
    {/if}
    <div class="rounded bg-surface-1 px-3 py-2 text-sm" data-testid="message-turn-assistant">
      {#if turn.thinking.length > 0}
        <details
          class="mb-2 rounded border border-border bg-surface-2"
          data-testid="message-turn-thinking"
        >
          <summary class="cursor-pointer px-2 py-1 text-xs text-fg-muted">Thinking</summary>
          <pre class="whitespace-pre-wrap px-2 py-1 text-xs text-fg-muted">{turn.thinking}</pre>
        </details>
      {/if}
      {#if bodyHtml.length > 0}
        <div class="message-turn__body" data-testid="message-turn-body">
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          {@html bodyHtml}
        </div>
      {:else if turn.body.length > 0}
        <p class="text-fg-muted" data-testid="message-turn-body-fallback">{turn.body}</p>
      {/if}
      <div class="mt-2 flex items-center justify-end gap-2">
        {#if turn.routing !== null}
          <RoutingBadge routing={turn.routing} />
        {/if}
      </div>
      {#if turn.error !== null}
        <p
          class="mt-2 rounded border border-red-500 px-2 py-1 text-xs text-red-400"
          data-testid="message-turn-error"
        >
          {CONVERSATION_STRINGS.errorBubbleLabel}: {turn.error}
        </p>
      {/if}
    </div>
  {/if}
</article>

<style>
  /* User bubble — soft brand-tinted surface to visually distinguish from
     assistant bubbles, matching v0.17.x's right-aligned user prompt style. */
  .user-bubble {
    background-color: rgb(var(--bearings-accent) / 0.14);
  }
</style>
