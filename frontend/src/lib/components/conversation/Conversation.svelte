<script lang="ts">
  /**
   * Main conversation pane — list of message turns + scroll anchor.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"opens an existing chat" — selecting
   *   a session reconnects this pane; the body renders message turns
   *   in chronological order.
   * - ``docs/behavior/tool-output-streaming.md`` §"Scroll-anchor
   *   behavior" — auto-scroll engages while the user is at the
   *   bottom; scrolling up disengages and surfaces the "Jump to
   *   bottom" affordance; scrolling back to the bottom re-engages.
   * - ``docs/behavior/tool-output-streaming.md`` §"Reconnect / replay" —
   *   the WS subscription resumes via ``since_seq`` from the
   *   conversation store's ``lastSeq``.
   * - Item 1.3 cursor pagination — session-open fetches the tail
   *   (``MESSAGE_PAGE_SIZE``); "Load older" walks backward by ``before=``.
   *
   * The pane is presentational + lifecycle: hydrate history on mount
   * + on session-id change, subscribe/disconnect via the agent WS
   * client, render the typed turns, manage scroll anchor.
   */
  import { onMount } from "svelte";

  import { connectSession, disconnectSession } from "../../agent.svelte";
  import { listMessages } from "../../api/messages";
  import { CONVERSATION_STRINGS, MESSAGE_PAGE_SIZE } from "../../config";
  import {
    conversationStore,
    hydrateTurns,
    loadOlder,
    resetConversation,
    setError,
    setLoading,
  } from "../../stores/conversation.svelte";
  import ApprovalModal from "./ApprovalModal.svelte";
  import AskUserQuestionModal from "./AskUserQuestionModal.svelte";
  import CheckpointGutter from "./CheckpointGutter.svelte";
  import LiveTodos from "./LiveTodos.svelte";
  import MessageTurn from "./MessageTurn.svelte";
  import ModelSelector from "./ModelSelector.svelte";
  import PermissionModeSelector from "./PermissionModeSelector.svelte";
  import StopUndoInline from "./StopUndoInline.svelte";
  import { checkpointBus } from "../../stores/checkpointBus.svelte";
  import { recoverSession } from "../../api/sessions";
  import { pasteIntoComposer } from "../../stores/composerBridge.svelte";

  interface Props {
    sessionId: string | null;
  }

  const { sessionId }: Props = $props();

  function handleAskForMoreDetail(): void {
    if (sessionId === null) return;
    pasteIntoComposer({
      sessionId,
      text: CONVERSATION_STRINGS.askForMoreDetailPrompt,
      kind: "link",
    });
  }

  let recovering = $state(false);

  async function handleRecover(): Promise<void> {
    if (sessionId === null || recovering) return;
    recovering = true;
    try {
      await recoverSession(sessionId);
      // error block clears via the session_upsert broadcast (error_pending=false)
    } catch {
      // Recovery failed — leave the error block visible; user can retry.
    } finally {
      recovering = false;
    }
  }

  let bodyEl: HTMLDivElement | null = $state(null);
  let atBottom = $state(true);
  let showJumpAffordance = $state(false);

  // ``true`` while the runner is streaming AND there is an open
  // assistant turn. Gating on ``streamingActive`` prevents an indefinite
  // spinner when the runner died mid-turn (item 1.4 ``runner_status``
  // sets ``streamingActive=false`` on reconnect, clearing the Stop
  // button even though the replay contains an uncompleted turn).
  const hasInFlightTurn = $derived(
    conversationStore.streamingActive &&
      conversationStore.turns.some((t) => t.role === "assistant" && !t.complete),
  );

  $effect(() => {
    const sid = sessionId;
    if (sid === null) {
      resetConversation(null);
      disconnectSession();
      return;
    }
    let cancelled = false;
    resetConversation(sid);
    setLoading(true);
    void (async () => {
      try {
        // Fetch only the tail on session-open (item 1.3) — keeps long
        // sessions from OOMing the tab. ``loadOlder()`` walks further back.
        const page = await listMessages(sid, { limit: MESSAGE_PAGE_SIZE });
        if (cancelled) return;
        hydrateTurns(sid, page);
      } catch (error) {
        if (cancelled) return;
        setError(error instanceof Error ? error : new Error(String(error)));
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (!cancelled) {
        connectSession(sid);
      }
    })();
    return () => {
      cancelled = true;
      disconnectSession();
    };
  });

  // Auto-scroll on each turn-list change while the user is at the
  // bottom (per behavior doc §"Scroll-anchor behavior"). The
  // ``conversationStore.turns`` proxy read inside the effect makes
  // this reactive without explicit subscriptions.
  $effect(() => {
    // Reactive read — without it Svelte 5 doesn't track this
    // dependency.
    void conversationStore.turns.length;
    if (bodyEl !== null && atBottom) {
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  });

  function handleScroll(): void {
    if (bodyEl === null) return;
    const dist = bodyEl.scrollHeight - bodyEl.scrollTop - bodyEl.clientHeight;
    // ~16px slack so a fractional-pixel scroll position still counts
    // as "at the bottom" (catches Hyprland HiDPI rounding).
    atBottom = dist < 16;
    showJumpAffordance = !atBottom;
  }

  function jumpToBottom(): void {
    if (bodyEl === null) return;
    bodyEl.scrollTop = bodyEl.scrollHeight;
    atBottom = true;
    showJumpAffordance = false;
  }

  function handleLoadOlder(): void {
    if (sessionId !== null) {
      void loadOlder(sessionId);
    }
  }

  onMount(() => {
    if (bodyEl !== null) {
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  });
</script>

<section class="conversation flex h-full flex-col" data-testid="conversation">
  <!-- Header bar — model selector + permission-mode selector; both hidden when no session active -->
  <div class="flex items-center justify-end gap-3 border-b border-border px-3 py-1">
    <ModelSelector {sessionId} />
    <PermissionModeSelector {sessionId} />
  </div>
  <!-- Live todos strip — sticky above the scroll body; hidden when empty -->
  <LiveTodos />
  <div class="relative flex-1 overflow-hidden">
    <div
      bind:this={bodyEl}
      class="conversation__body h-full overflow-y-auto"
      data-testid="conversation-body"
      onscroll={handleScroll}
    >
      {#if conversationStore.hasMore}
        <div class="flex justify-center py-2">
          <button
            type="button"
            class="rounded bg-surface-2 px-3 py-1 text-xs text-fg-muted hover:text-fg-strong disabled:opacity-50"
            data-testid="conversation-load-older"
            disabled={conversationStore.loadingOlder}
            onclick={handleLoadOlder}
          >
            {conversationStore.loadingOlder
              ? CONVERSATION_STRINGS.loadingOlder
              : CONVERSATION_STRINGS.loadOlderLabel}
          </button>
        </div>
      {/if}

      {#if conversationStore.loading && conversationStore.turns.length === 0}
        <p class="px-4 py-3 text-sm text-fg-muted" data-testid="conversation-loading">
          {CONVERSATION_STRINGS.loadingTranscript}
        </p>
      {:else if conversationStore.error !== null}
        <div
          class="flex flex-col gap-2 border-l-4 border-red-500 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300"
          data-testid="conversation-error"
          role="alert"
        >
          <p class="font-medium">{CONVERSATION_STRINGS.errorBubbleLabel}</p>
          <p class="text-xs">{conversationStore.error.message}</p>
          <p class="text-xs text-red-600 dark:text-red-400">
            {CONVERSATION_STRINGS.errorHintLabel}
          </p>
          {#if sessionId !== null}
            <button
              type="button"
              class="mt-1 self-start rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              disabled={recovering}
              onclick={handleRecover}
              data-testid="conversation-recover-btn"
            >
              {recovering
                ? CONVERSATION_STRINGS.recoveringLabel
                : CONVERSATION_STRINGS.recoverLabel}
            </button>
          {/if}
        </div>
      {:else if conversationStore.turns.length === 0}
        <p class="px-4 py-3 text-sm text-fg-muted" data-testid="conversation-empty">
          {CONVERSATION_STRINGS.emptyTranscript}
        </p>
      {:else}
        {#each conversationStore.turns as turn (turn.id)}
          <MessageTurn {turn} {sessionId} onAskForMoreDetail={handleAskForMoreDetail} />
        {/each}
      {/if}
    </div>
    <CheckpointGutter {sessionId} {bodyEl} refreshKey={checkpointBus.refreshKey} />
  </div>

  {#if hasInFlightTurn && sessionId !== null}
    <StopUndoInline {sessionId} />
  {/if}

  {#if showJumpAffordance}
    <button
      type="button"
      class="conversation__jump self-end rounded bg-surface-2 px-3 py-1 text-xs text-fg-strong shadow"
      data-testid="conversation-jump-to-bottom"
      onclick={jumpToBottom}
    >
      {CONVERSATION_STRINGS.scrollToBottomLabel}
    </button>
  {/if}
</section>

{#if conversationStore.pendingApproval !== null && sessionId !== null}
  {#if conversationStore.pendingApproval.toolName === "AskUserQuestion"}
    <AskUserQuestionModal {sessionId} approval={conversationStore.pendingApproval} />
  {:else}
    <ApprovalModal {sessionId} approval={conversationStore.pendingApproval} />
  {/if}
{/if}
