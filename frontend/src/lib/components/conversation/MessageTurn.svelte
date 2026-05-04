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
   * - ``docs/behavior/context-menus.md`` §"Message bubble" — nine
   *   context-menu actions wired via ``use:contextMenu`` (G3).
   *
   * The component is presentational: receives a ``MessageTurnView``
   * and renders it. The reducer produces these views; the parent
   * Conversation component iterates the list.
   */
  import {
    CONVERSATION_STRINGS,
    MENU_ACTION_MESSAGE_COPY_AS_MARKDOWN,
    MENU_ACTION_MESSAGE_COPY_CONTENT,
    MENU_ACTION_MESSAGE_COPY_ID,
    MENU_ACTION_MESSAGE_DELETE,
    MENU_ACTION_MESSAGE_FORK_FROM_HERE,
    MENU_ACTION_MESSAGE_HIDE_FROM_CONTEXT,
    MENU_ACTION_MESSAGE_JUMP_TO_TURN,
    MENU_ACTION_MESSAGE_MOVE_TO_SESSION,
    MENU_ACTION_MESSAGE_PIN,
    MENU_ACTION_MESSAGE_REGENERATE,
    MENU_ACTION_MESSAGE_REGENERATE_IN_PLACE,
    MENU_ACTION_MESSAGE_SPLIT_HERE,
    MENU_TARGET_MESSAGE,
  } from "../../config";
  import { goto } from "$app/navigation";
  import { contextMenu } from "../../actions/contextMenu";
  import { markdownContextMenu } from "../../actions/markdownContextMenu";
  import { createCheckpoint, forkCheckpoint } from "../../api/checkpoints";
  import {
    deleteMessage,
    moveMessage,
    patchMessageHidden,
    patchMessagePinned,
  } from "../../api/messages";
  import { regenerateSession } from "../../api/sessions";
  import { linkifyToHtml } from "../../linkify";
  import { renderMarkdown } from "../../render";
  import { sanitizeHtml } from "../../sanitize";
  import { bumpCheckpointRefresh } from "../../stores/checkpointBus.svelte";
  import type { MessageTurnView } from "../../stores/conversation.svelte";
  import ConfirmDialog from "../sidebar/ConfirmDialog.svelte";
  import RoutingBadge from "./RoutingBadge.svelte";
  import ToolOutput from "./ToolOutput.svelte";

  interface Props {
    turn: MessageTurnView;
    sessionId?: string | null;
    onAskForMoreDetail?: () => void;
  }

  const { turn, sessionId, onAskForMoreDetail }: Props = $props();

  function handleAskForMoreDetail(): void {
    onAskForMoreDetail?.();
  }

  async function handleRegenerate(): Promise<void> {
    if (sessionId === null || sessionId === undefined) return;
    try {
      await regenerateSession(sessionId);
      // Toast feedback handled by the API consumer or parent component
    } catch (err) {
      console.error("Regenerate failed:", err);
    }
  }

  // ---- context-menu action state -----------------------------------------

  let showDeleteConfirm = $state(false);

  // ---- context-menu handlers ---------------------------------------------

  const menuHandlers = $derived({
    /** Scroll the article element into view. */
    [MENU_ACTION_MESSAGE_JUMP_TO_TURN]: () => {
      const el = document.querySelector(`[data-turn-id="${CSS.escape(turn.id)}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    },

    /** Copy the plain-text message body to the clipboard. */
    [MENU_ACTION_MESSAGE_COPY_CONTENT]: () => {
      void navigator.clipboard.writeText(turn.body);
    },

    /**
     * Copy the message as Markdown with role + timestamp header.
     * Advanced action — Shift+right-click only.
     */
    [MENU_ACTION_MESSAGE_COPY_AS_MARKDOWN]: () => {
      const header = `**${turn.role}** (${turn.createdAt})\n\n`;
      void navigator.clipboard.writeText(header + turn.body);
    },

    /** Copy the message ID. Advanced action. */
    [MENU_ACTION_MESSAGE_COPY_ID]: () => {
      void navigator.clipboard.writeText(turn.id);
    },

    /** Pin the message bubble to the conversation header. */
    [MENU_ACTION_MESSAGE_PIN]: () => {
      void patchMessagePinned(turn.id, true).catch((err) => {
        console.error("Pin message failed:", err);
      });
    },

    /**
     * Hide the message from the context window so it is excluded from
     * the next prompt. Advanced action.
     */
    [MENU_ACTION_MESSAGE_HIDE_FROM_CONTEXT]: () => {
      void patchMessageHidden(turn.id, true).catch((err) => {
        console.error("Hide message failed:", err);
      });
    },

    /**
     * Move the message to another session. Uses window.prompt for the
     * session ID until a full session-picker UI lands in a later item.
     */
    [MENU_ACTION_MESSAGE_MOVE_TO_SESSION]: () => {
      // Simple session-ID prompt; a full session-picker is deferred.
      const targetId = window.prompt("Enter target session ID:");
      if (targetId === null || targetId.trim() === "") return;
      void moveMessage(turn.id, targetId.trim()).catch((err) => {
        console.error("Move message failed:", err);
      });
    },

    /**
     * Split the conversation at this message — drop a checkpoint at
     * this anchor (G6). Per ``docs/behavior/context-menus.md``
     * §"Message bubble" split-here records the boundary; the user can
     * fork from the gutter chip later if they decide to branch.
     */
    [MENU_ACTION_MESSAGE_SPLIT_HERE]: () => {
      if (sessionId === null || sessionId === undefined) return;
      void (async () => {
        try {
          await createCheckpoint({ sessionId, messageId: turn.id });
          bumpCheckpointRefresh();
        } catch (err) {
          console.error("split-here failed:", err);
        }
      })();
    },

    /**
     * Fork a new session from this message onward (G6) — create a
     * checkpoint here, then immediately fork it. Navigates to the new
     * session on success. Per ``docs/behavior/context-menus.md``
     * §"Message bubble" + §"Checkpoint (gutter chip)".
     */
    [MENU_ACTION_MESSAGE_FORK_FROM_HERE]: () => {
      if (sessionId === null || sessionId === undefined) return;
      void (async () => {
        try {
          const cp = await createCheckpoint({ sessionId, messageId: turn.id });
          bumpCheckpointRefresh();
          const result = await forkCheckpoint(cp.id);
          await goto(`/sessions/${encodeURIComponent(result.new_session_id)}`);
        } catch (err) {
          console.error("fork-from-here failed:", err);
        }
      })();
    },

    [MENU_ACTION_MESSAGE_REGENERATE]: () => void handleRegenerate(),
    [MENU_ACTION_MESSAGE_REGENERATE_IN_PLACE]: () => void handleRegenerate(),

    /** Show the delete confirmation dialog. Advanced + destructive action. */
    [MENU_ACTION_MESSAGE_DELETE]: () => {
      showDeleteConfirm = true;
    },
  });

  async function handleDeleteConfirm(): Promise<void> {
    showDeleteConfirm = false;
    try {
      await deleteMessage(turn.id);
    } catch (err) {
      console.error("Delete message failed:", err);
    }
  }

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

{#if showDeleteConfirm}
  <ConfirmDialog
    message="Delete this message? This cannot be undone."
    confirmLabel="Delete"
    onConfirm={() => void handleDeleteConfirm()}
    onCancel={() => {
      showDeleteConfirm = false;
    }}
  />
{/if}

<article
  class="message-turn flex flex-col gap-2 px-4 py-4"
  data-testid="message-turn"
  data-turn-id={turn.id}
  data-role={turn.role}
  use:contextMenu={{
    target: MENU_TARGET_MESSAGE,
    handlers: menuHandlers,
    data: { messageId: turn.id, sessionId },
  }}
>
  {#if turn.role === "user"}
    <div class="flex flex-col items-end gap-1">
      {#if turn.resumed}
        <span
          class="text-xs text-fg-muted"
          data-testid="message-turn-resumed"
          title="This prompt was re-queued and replayed to the runner after a restart"
        >
          {CONVERSATION_STRINGS.turnResumedLabel}
        </span>
      {/if}
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
    <div
      class="group relative rounded bg-surface-1 px-3 py-2 text-sm"
      data-testid="message-turn-assistant"
    >
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
        <div class="message-turn__body" data-testid="message-turn-body" use:markdownContextMenu>
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          {@html bodyHtml}
        </div>
      {:else if turn.body.length > 0}
        <p class="text-fg-muted" data-testid="message-turn-body-fallback">{turn.body}</p>
      {/if}
      <div class="mt-2 flex items-center justify-end gap-2">
        <button
          type="button"
          class="opacity-0 transition-opacity group-hover:opacity-100"
          title={CONVERSATION_STRINGS.askForMoreDetailLabel}
          onclick={handleAskForMoreDetail}
          data-testid="message-turn-ask-for-detail"
        >
          <svg
            class="h-4 w-4 text-fg-muted hover:text-fg-strong"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </button>
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
