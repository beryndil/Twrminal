<script lang="ts" module>
  /**
   * A lightweight turn for the compact checklist-chat panel. Exported
   * so unit tests can build stubs without re-declaring the shape.
   */
  export interface ChatTurn {
    id: string;
    role: "user" | "assistant";
    body: string;
    /** True while the assistant is actively streaming this turn. */
    streaming: boolean;
  }
</script>

<script lang="ts">
  /**
   * ChecklistChat — compact whole-list conversational surface rendered
   * above the checklist items tree inside a checklist session pane.
   *
   * Behavior anchor: ``docs/behavior/checklists.md`` §ChecklistChat.
   *
   * Renders user / assistant turn pairs for the checklist session
   * itself (not per-item paired chats). The textarea + Send button
   * drives ``POST /api/sessions/{checklistId}/prompt``; live streaming
   * deltas arrive via a per-component WebSocket subscription to
   * ``/ws/sessions/{checklistId}``.
   *
   * All network calls are injectable for unit testing — pass stubs via
   * the seam props.
   */
  import { ApiError } from "../../api/client";
  import { listMessages as listMessagesDefault } from "../../api/messages";
  import { sendPrompt as sendPromptDefault } from "../../api/prompt";
  import { parseStreamFrame } from "../../api/streaming";
  import { CHECKLIST_STRINGS, sessionStreamPath, WS_FRAME_KIND_EVENT } from "../../config";

  /**
   * Return a real ``WebSocket`` factory when the global is available,
   * or ``null`` in environments where WebSocket is not supported
   * (e.g. JSDOM in unit tests). Evaluated once at component init.
   */
  function defaultWsFactory(): ((url: string) => WebSocket) | null {
    if (typeof globalThis.WebSocket !== "undefined") {
      return (url: string) => new WebSocket(url);
    }
    return null;
  }

  interface Props {
    /** The checklist session id — also the WS subscription target. */
    checklistId: string;
    /**
     * WebSocket factory. ``null`` disables streaming (no socket created).
     * Defaults to ``new WebSocket(url)`` when the global is available.
     * Tests pass a mock factory to capture the message handler.
     */
    createWs?: ((url: string) => WebSocket) | null;
    /** Injected for unit testing — defaults to the real API call. */
    sendPromptFn?: typeof sendPromptDefault;
    /** Injected for unit testing — defaults to the real API call. */
    listMessagesFn?: typeof listMessagesDefault;
  }

  const {
    checklistId,
    createWs = defaultWsFactory(),
    sendPromptFn = sendPromptDefault,
    listMessagesFn = listMessagesDefault,
  }: Props = $props();

  let turns = $state<ChatTurn[]>([]);
  let draft = $state("");
  let inflight = $state(false);
  let errorMessage = $state<string | null>(null);

  const canSend = $derived(!inflight && draft.trim().length > 0);

  // ---------------------------------------------------------------------------
  // WebSocket
  // ---------------------------------------------------------------------------

  function buildWsUrl(sessionId: string): string {
    const path = sessionStreamPath(sessionId);
    return typeof window === "undefined"
      ? `ws://localhost${path}`
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}${path}`;
  }

  function handleWsMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") return;
    const frame = parseStreamFrame(event.data);
    if (frame === null || frame.kind !== WS_FRAME_KIND_EVENT) return;
    const e = frame.event;
    switch (e.type) {
      case "user_message":
        // Guard against duplicates — the optimistic turn may already be
        // present if the WS message arrives before the UI re-renders.
        if (!turns.some((t) => t.id === e.message_id)) {
          turns = [...turns, { id: e.message_id, role: "user", body: e.content, streaming: false }];
        }
        break;
      case "message_start":
        turns = [...turns, { id: e.message_id, role: "assistant", body: "", streaming: true }];
        break;
      case "token":
        turns = turns.map((t) => (t.id === e.message_id ? { ...t, body: t.body + e.delta } : t));
        break;
      case "message_complete":
        turns = turns.map((t) =>
          t.id === e.message_id ? { ...t, body: e.content, streaming: false } : t,
        );
        break;
      default:
        // Heartbeats and unrelated events (tool calls, routing badges, etc.)
        // are intentionally ignored — the chat panel only renders text turns.
        break;
    }
  }

  // ---------------------------------------------------------------------------
  // Hydration
  // ---------------------------------------------------------------------------

  async function hydrate(sessionId: string): Promise<void> {
    try {
      const page = await listMessagesFn(sessionId, { limit: 50 });
      turns = page.items
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          body: m.content,
          streaming: false,
        }));
    } catch {
      // Network / API error on hydration — the panel stays usable for
      // new messages. Error state is intentionally not surfaced so the
      // user can still send instructions even when history is unavailable.
    }
  }

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  async function handleSend(): Promise<void> {
    const content = draft.trim();
    if (!content || inflight) return;
    draft = "";
    inflight = true;
    errorMessage = null;
    // Optimistic user bubble — removed if the 202 handshake fails.
    const optimisticId = `opt-${Date.now().toString()}`;
    turns = [...turns, { id: optimisticId, role: "user", body: content, streaming: false }];
    try {
      await sendPromptFn(checklistId, content);
      // 202 queued. Assistant turn streams in via the WS subscription.
    } catch (err) {
      turns = turns.filter((t) => t.id !== optimisticId);
      if (err instanceof ApiError) {
        errorMessage = `Send failed (${err.status.toString()}).`;
      } else {
        errorMessage = err instanceof Error ? err.message : "Send failed.";
      }
    } finally {
      inflight = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  $effect(() => {
    // Hydrate history and open the WS stream when checklistId changes.
    // The cleanup fn returned here runs before the next effect execution
    // (prop change) and on component unmount, closing the previous socket.
    void hydrate(checklistId);
    let socket: WebSocket | null = null;
    if (createWs !== null) {
      try {
        socket = createWs(buildWsUrl(checklistId));
        socket.addEventListener("message", handleWsMessage);
      } catch {
        // WS unavailable in this runtime — streaming is disabled
        // gracefully; the panel still accepts and sends prompts.
      }
    }
    return (): void => {
      if (socket !== null) {
        socket.removeEventListener("message", handleWsMessage);
        socket.close();
      }
    };
  });
</script>

<section
  class="checklist-chat flex max-h-40 flex-col border-b border-border"
  data-testid="checklist-chat"
  aria-label={CHECKLIST_STRINGS.chatPanelAriaLabel}
>
  <div
    class="checklist-chat__turns flex-1 overflow-y-auto px-3 py-2 text-sm"
    data-testid="checklist-chat-turns"
  >
    {#each turns as turn (turn.id)}
      <div
        class="checklist-chat__turn mb-1 whitespace-pre-wrap {turn.role === 'user'
          ? 'text-right'
          : 'text-fg-muted'}"
        data-testid="checklist-chat-turn"
        data-role={turn.role}
      >
        {turn.body}{#if turn.streaming}<span
            class="checklist-chat__cursor animate-pulse"
            data-testid="checklist-chat-cursor"
            aria-hidden="true">▌</span
          >{/if}
      </div>
    {/each}
    {#if errorMessage !== null}
      <p class="text-xs text-red-400" data-testid="checklist-chat-error">{errorMessage}</p>
    {/if}
  </div>

  <div class="checklist-chat__composer flex items-end gap-1 border-t border-border px-2 py-1">
    <textarea
      class="checklist-chat__input flex-1 resize-none rounded bg-surface-2 px-2 py-1 text-sm"
      rows="2"
      placeholder={CHECKLIST_STRINGS.chatInputPlaceholder}
      aria-label={CHECKLIST_STRINGS.chatInputAriaLabel}
      data-testid="checklist-chat-input"
      bind:value={draft}
      disabled={inflight}
      onkeydown={(event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          void handleSend();
        }
      }}
    ></textarea>
    <button
      type="button"
      class="checklist-chat__send rounded bg-surface-2 px-2 py-1 text-sm disabled:opacity-40"
      aria-label={CHECKLIST_STRINGS.chatSendAriaLabel}
      data-testid="checklist-chat-send"
      disabled={!canSend}
      onclick={() => void handleSend()}
    >
      {CHECKLIST_STRINGS.chatSendLabel}
    </button>
  </div>
</section>
